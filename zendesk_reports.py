#!/usr/bin/env python

"""Warn if the bug-report rate has increased recently, on Zendesk.

While we used to ask users to report problems on a google code issues
page, and then UserVoice, we now use Zendesk:
   https://khanacademy.zendesk.com/

Zendesk supports an API for getting all the tickets ever opened, but
we use the incremental API to get all tickets reported since last time.
"""

import base64
import cPickle
import datetime
import json
import httplib
import logging
import socket
import time
import urllib2

import util

# In theory, you can use an API key to access zendesk data, but I
# couldn't get it to work in my tests (I got 'access denied'), so we
# use the real password instead. :-(
ZENDESK_USER = 'prod-read@khanacademy.org'
ZENDESK_PASSWORD_FILE = util.relative_path("zendesk.cfg")
ZENDESK_PASSWORD = None     # set lazily

# This is the currently defined boundary for what is considered
# 'significant' in number of new tickets. Used as threshold to determine
# when to send alerts.
SIGNIFICANT_TICKET_COUNT = 5


def _parse_time(s):
    """Convert a string of the form "YYYY-MM-DD HH:MM:SS -0700" to time_t.

    We ignore the -0700; it looks like all times (and time_t's!)
    reported by the API are given as PDT times, so I'm assuming
    they'll change appropriately when daylight savings time ends.
    """
    # We could use strptime, but this is just as easy.
    (yyyy, mm, dd, HH, MM, SS) = (int(s[0:4]), int(s[5:7]), int(s[8:10]),
                                  int(s[11:13]), int(s[14:16]), int(s[17:19]))
    return time.mktime((yyyy, mm, dd, HH, MM, SS, 0, 0, -1))


def get_ticket_data(start_time_t):
    """Given start_time to export from, call Zendesk API for ticket data."""
    global ZENDESK_PASSWORD
    if ZENDESK_PASSWORD is None:
        with open(ZENDESK_PASSWORD_FILE) as f:
            ZENDESK_PASSWORD = f.read().strip()

    # According to
    #   http://developer.zendesk.com/documentation/rest_api/ticket_export.html
    # "Requests with a start_time less than 5 minutes old will also
    # be rejected."
    if int(time.time()) - start_time_t <= 300:
        return None

    url = ('https://khanacademy.zendesk.com/api/v2/exports/tickets.json'
           '?start_time=%s' % start_time_t)
    request = urllib2.Request(url)
    # This is the best way to set the user, according to
    #    http://stackoverflow.com/questions/2407126/python-urllib2-basic-auth-problem
    encoded_password = base64.standard_b64encode('%s:%s' % (ZENDESK_USER,
                                                            ZENDESK_PASSWORD))
    request.add_unredirected_header('Authorization',
                                    'Basic %s' % encoded_password)

    def _should_retry(exc):
        if isinstance(exc, urllib2.HTTPError) and exc.code == 429:
            # quota limits: try again, but wait first.
            time.sleep(int(exc.headers['Retry-After']))
        return isinstance(exc, (socket.error, urllib2.HTTPError,
                                httplib.HTTPException))

    data = util.retry(lambda: urllib2.urlopen(request, timeout=60),
                      'loading zendesk ticket data',
                      _should_retry)

    return json.load(data)


def num_tickets_between(start_time_t, end_time_t):
    """Return the number of tickets created between start and end time.

    Also return the time of the oldest ticket seen, as a time_t, which
    is useful for getting an actual date-range when start_time is 0.
    """
    num_tickets = 0
    oldest_ticket_time_t = None

    while start_time_t < end_time_t:
        ticket_data = get_ticket_data(start_time_t)
        if not ticket_data:
            break

        for ticket in ticket_data['results']:
            # we only care about technical issues
            if 'technical_issue' not in ticket['current_tags']:
                continue

            # Skip tickets created by user-support, since they are
            # submitted in batches and cause false alarms
            if 'Request created from:' in ticket['subject']:
                continue

            ticket_time_t = _parse_time(ticket['created_at'])
            if ticket_time_t > end_time_t or ticket_time_t <= start_time_t:
                continue
            num_tickets += 1
            # See if we're the oldest ticket
            if (oldest_ticket_time_t is None or
                    oldest_ticket_time_t > ticket_time_t):
                oldest_ticket_time_t = ticket_time_t

        if not ticket_data['next_page']:
            break
        start_time_t = ticket_data['end_time']

    return (num_tickets, oldest_ticket_time_t)


def handle_alerts(num_new_tickets,
                  time_this_period,
                  mean,
                  probability,
                  start_time,
                  end_time):
    """Determine which alerts to send at various thresholds.

    If probability of elevated ticket count is high, a notification
    is sent to Slack and Alerta. A Pagerduty alert is only sent out
    if a significantly elevated rate is detected.
    """
    # TODO(jacqueline): Including SIGNIFICANT_TICKET_COUNT hard
    # threshold here so as to catch false positives, especially during
    # transition. Maybe consider removing this once change in mean
    # starts flattening out; August 2017?
    message = (
            "We saw %s in the last %s minutes,"
            " while the mean indicates we should see around %s."
            " *Probability that this is abnormally elevated: %.4f.*"
            % (util.thousand_commas(num_new_tickets),
               util.thousand_commas(int(time_this_period / 60)),
               util.thousand_commas(round(mean, 2)),
               probability))

    if (mean != 0 and probability > 0.999 and
            num_new_tickets >= SIGNIFICANT_TICKET_COUNT):
        # Too many errors!  Point people to the slack channel.
        message = "Elevated Zendesk report rate (#zendesk-tickets)\n" + message

        util.send_to_slack(message, channel='#1s-and-0s')
        util.send_to_slack(message, channel='#user-issues')
        util.send_to_alerta(message, severity=logging.ERROR)

        # Before we start texting people, make sure we've hit higher threshold.
        # TODO(benkraft/jacqueline): Potentially could base this off more
        # historical data from analogous dow/time datapoints, but doesn't look
        # like Zendesk API has a good way of doing this, running into request
        # quota issues. Readdress this option if threshold is too noisy.
        if probability > 0.9995:
            util.send_to_pagerduty(message, service='beep-boop')
    else:
        # If ticket rate is normal, still send alert to alerta to resolve any
        # prior existing alerts.
        message = "Normal Zendesk report rate (#zendesk-tickets)\n" + message
        util.send_to_alerta(message, severity=logging.INFO, mark_resolved=True)


def _is_off_hours(dt):
    """Returns whether we consider this time to be "off hours".

    We consider weekends and evenings to be off-hours, and track separate
    metrics for them, so that we aren't oversensitive during the weekday and
    undersensitive otherwise.

    Arguments: dt should be a datetime.datetime object, in Pacific Time (PDT or
    PST, whichever is currently active).

    TODO(benkraft): Something smarter and more adaptive to what the real data
    looks like.
    """
    if dt.weekday() in [5, 6]:
        return True
    # These times were chosen by the very precise method of "eyeballing it" on
    # number of tickets per hour in the week I happened to look.  We follow US
    # Daylight Savings Time because we figure that's where most users are.
    elif 6 <= dt.hour <= 19:
        return False
    else:
        return True


def main():
    try:
        zendesk_status_file = util.relative_path("zendesk")
        with open(zendesk_status_file) as f:
            old_data = cPickle.load(f)
    except IOError:
        old_data = {"elapsed_time_weekday": 0.0001,   # avoid a divide-by-0
                    "elapsed_time_weekend": 0.0001,   # avoid a divide-by-0
                    "ticket_count_weekday": 0,
                    "ticket_count_weekend": 0,
                    "last_time_t_weekday": None,
                    "last_time_t_weekend": None,
                    }

    # We compare the number of tickets in the last few minutes against
    # the historical average for all time.  But we don't start "all
    # time" at AD 1, we start it a week ago.  Longer than that and it
    # takes forever due to quota issues.  That's still plenty of
    # historical data. :-)
    #
    # Zendesk seems to wait 5 minutes to update API data :-(, so we
    # ask for data that's a bit time-lagged
    end_time = int(time.time()) - 300
    start_time = old_data['last_time_t']

    # Set flag to track if current time period is a weekend. Separate
    # ticket_count/elapsed_time stats are kept for weekend vs. weekday
    # to improve sensitivity to increases during low-traffic periods
    is_off_hours = _is_off_hours(datetime.datetime.fromtimestamp(end_time))

    (num_new_tickets, oldest_ticket_time_t) = num_tickets_between(
        start_time or (end_time - 86400 * 7), end_time)

    # The first time we run this, we take the starting time to be the
    # time of the first bug report.

    if start_time is None:
        start_time = oldest_ticket_time_t

    time_this_period = end_time - start_time

    if is_off_hours:
        # To simplify backcompat we still use "weekend" and "weekday" in the
        # saved data; really they mean "on hours" and "off hours" now.
        ticket_count = old_data['ticket_count_weekend']
        elapsed_time = old_data['elapsed_time_weekend']
    else:
        ticket_count = old_data['ticket_count_weekday']
        elapsed_time = old_data['elapsed_time_weekday']

    (mean, probability) = util.probability(ticket_count,
                                           elapsed_time,
                                           num_new_tickets,
                                           time_this_period)

    print ("%s] TOTAL %s/%ss; %s-: %s/%ss; m=%.3f p=%.3f"
           % (time.strftime("%Y-%m-%d %H:%M:%S %Z"),
              ticket_count, int(elapsed_time),
              start_time,
              num_new_tickets, time_this_period,
              mean, probability))

    handle_alerts(num_new_tickets, time_this_period, mean, probability,
                  start_time, end_time)

    if is_off_hours:
        new_data = {"elapsed_time_weekend": (
                        old_data["elapsed_time_weekend"] + time_this_period),
                    "ticket_count_weekend": (
                        old_data["ticket_count_weekend"] + num_new_tickets),
                    "elapsed_time_weekday": old_data["elapsed_time_weekday"],
                    "ticket_count_weekday": old_data["ticket_count_weekday"],
                    }
    else:
        new_data = {"elapsed_time_weekend": old_data["elapsed_time_weekend"],
                    "ticket_count_weekend": old_data["ticket_count_weekend"],
                    "elapsed_time_weekday": (
                        old_data["elapsed_time_weekday"] + time_this_period),
                    "ticket_count_weekday": (
                        old_data["ticket_count_weekday"] + num_new_tickets),
                    }

    new_data['last_time_t'] = end_time

    with open(zendesk_status_file, 'w') as f:
        cPickle.dump(new_data, f)


if __name__ == "__main__":
    main()
