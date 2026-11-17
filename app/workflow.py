from . import coordination
from . import assistance
from . import notices

OPERATIONS={
    'coordination.open_case':coordination.open_case,
    'assistance.allocate':assistance.allocate,
    'notices.send':notices.send,
}
