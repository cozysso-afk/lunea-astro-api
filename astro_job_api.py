from __future__ import annotations

from astro_api import app
from astro_jobs_v1 import install_astro_jobs
from profile_auto_api import install_profile_auto
from vedic_api import install_vedic_api

install_astro_jobs(app)
install_profile_auto(app)
install_vedic_api(app)
