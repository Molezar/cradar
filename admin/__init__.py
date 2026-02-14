from .commands import setup_admin_commands
from .callbacks import setup_admin_callbacks

def setup_admin(dp):
    setup_admin_commands(dp)
    setup_admin_callbacks(dp)