# __init__.py
from .commands import setup_admin_commands
from .callbacks import setup_admin_callbacks
from .messages import setup_admin_messages 

def setup_admin(dp):
    setup_admin_commands(dp)
    setup_admin_callbacks(dp)
    setup_admin_messages(dp)