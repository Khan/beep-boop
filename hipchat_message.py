import datetime
import sys

import hipchat.room
import hipchat.config


def send_message(msg, room_id="1s and 0s"):
    result = ""
    msg_dict = {
        "room_id": room_id,
        "from": "beep-boop",
        "message": msg,
        "color": "red",
    }

    try:
        result = str(hipchat.room.Room.message(**msg_dict))
    except:
        pass

    format_args = (datetime.datetime.now(), msg, room_id)
    if "sent" in result:
        print "At %s, sent message '%s' to room '%s'" % format_args
    else:
        print >> sys.stderr, ("At %s, FAILED to send message '%s' to room '%s'"
                              % format_args)
        print >> sys.stderr, "Result from hipchat: %s" % result

hipchat.config.init_cfg("hipchat.cfg")
