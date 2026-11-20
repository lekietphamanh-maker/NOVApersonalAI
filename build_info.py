"""Which build this is. CI overwrites BUILD with the commit and VERSION with the release ("v2.2.0") before packaging;
from source both stay "dev", and a "dev" Nova never updates itself."""
BUILD = "dev"
VERSION = "dev"
