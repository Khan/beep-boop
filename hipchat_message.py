import contextlib
import datetime
import re
import sys
import urllib2

import util

with open(util.relative_path("hipchat.cfg")) as cfg_file:
    contents = cfg_file.read()
    # This assumes that there is a token defined in hipchat.cfg; if there isn't
    # we can't send anyway, so it's better to fail loudly.
    token_re = re.compile("token ?= ?([0-9A-Fa-f]+)")
    TOKEN = token_re.match(contents).group(1)


def send_message(msg, room_id="1s and 0s"):
    msg_params = ("room_id=%s" % room_id +
                  "&from=beep-boop" +
                  "&message=%s" % msg +
                  "&color=red")

    try:
        url = (
            "http://api.hipchat.com/v1/rooms/message?format=json&auth_token=%s"
            % TOKEN)
        with contextlib.closing(urllib2.urlopen(url, msg_params)) as req:
            result = req.read()
    except urllib2.HTTPError, err:
        result = err

    format_args = (datetime.datetime.now(), msg, room_id)
    if "sent" in result:
        print "At %s, sent message '%s' to room '%s'" % format_args
    else:
        print >> sys.stderr, ("At %s, FAILED to send message '%s' to room '%s'"
                              % format_args)
        print >> sys.stderr, "Result from hipchat: %s" % result
