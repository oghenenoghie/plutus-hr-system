from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.core.db_roles import grant_app_role
from app.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The app's own settings are the source of truth for the DB URL — never a
# hardcoded value in alembic.ini, so migrations always run against whatever
# the environment provides: MIGRATION_DATABASE_URL (the role that owns the
# tables) when the application connects as a separate ordinary role, else
# DATABASE_URL. A caller that already set a URL (the test suite, the desktop
# entrypoint) keeps it.
if not config.get_main_option("sqlalchemy.url"):
    settings = get_settings()
    config.set_main_option(
        "sqlalchemy.url", settings.migration_database_url or settings.database_url
    )

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    app_role = get_settings().app_database_role
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()
            # Keep the application's ordinary role able to use every table,
            # including any this run just created.
            if app_role:
                grant_app_role(connection, role=app_role)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
