def register(ctx):
    from .adapter import register as register_platform
    from .mattermost_context import register as register_thread_context
    from .cli import setup_parser, command, ensure_template, refresh_project_knowledge
    from hermes_constants import get_default_hermes_root, get_hermes_home
    register_platform(ctx)
    register_thread_context(ctx)
    ctx.register_cli_command(name="gitlab", help="Manage GitLab project profiles and repository routes",
                             setup_fn=setup_parser, handler_fn=command)
    if get_hermes_home().resolve() == get_default_hermes_root().resolve():
        ensure_template()
        refresh_project_knowledge(get_default_hermes_root())
