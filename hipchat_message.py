import hipchat.room
import hipchat.config


def message_ones_and_zeros(msg):
    result = ""
    msg_dict = {
        "room_id": 82909,  # ID of 1s and 0s
        "from": "beep-boop",
        "message": msg,
        "color": "red",
    }

    try:
        result = str(hipchat.room.Room.message(**msg_dict))
    except:
        pass

    if "sent" in result:
        print "Notified Hipchat room 1s and 0s message %s" % msg
    else:
        print "Failed to send message to Hipchat room 1s and 0s: %s" % msg

hipchat.config.init_cfg("hipchat.cfg")
