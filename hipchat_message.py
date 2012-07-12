import datetime

import hipchat.room
import hipchat.config


def message_ones_and_zeros(msg, room_id="1s and 0s", room_name="1s and 0s"):
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

    format_args = (datetime.datetime.now(), msg, room_name) 
    if "sent" in result:
        print "At %s, sent message '%s' to room '%s'" % format_args
    else:
        print "At %s, FAILED to send message '%s' to room '%s'" % format_args

hipchat.config.init_cfg("hipchat.cfg")
