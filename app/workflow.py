from . import coordination
from . import assistance
from . import corrections
from . import notices

OPERATIONS={
    'coordination.open_case':coordination.open_case,
    'assistance.allocate':assistance.allocate,
    'events.reassign':corrections.reassign,
    'notices.send':notices.send,
}
