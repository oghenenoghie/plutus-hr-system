from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory storage (slowapi's default) — fine for a single Railway
# replica; would need a shared backend (e.g. Redis) to hold across
# multiple replicas, which this deployment doesn't run yet.
limiter = Limiter(key_func=get_remote_address)
