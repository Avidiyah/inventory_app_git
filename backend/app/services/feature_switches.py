"""App-wide on/off switches (`feature_switches` table). A missing row is off.

`SMR` hides the SMR27 audit everywhere while off: the `/work-orders/smr/*`
routes answer 404 and the SPA drops the SMR27 and SMR Admin Review pages and
the Integrations SMR imports (it reads `smr_enabled` off `/auth/me`)."""

from sqlalchemy.orm import Session

from app.models import FeatureSwitch

SMR = "smr"


def is_enabled(db: Session, key: str) -> bool:
    row = db.get(FeatureSwitch, key)
    return bool(row and row.enabled)


def set_enabled(db: Session, key: str, enabled: bool) -> bool:
    row = db.get(FeatureSwitch, key)
    if row is None:
        db.add(FeatureSwitch(key=key, enabled=enabled))
    else:
        row.enabled = enabled
    db.commit()
    return enabled
