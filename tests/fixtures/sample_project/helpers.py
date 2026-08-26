# Fixture file: helpers.py
#
# EXPECTED-INCLUDE: helpers.slugify
# EXPECTED-INCLUDE: helpers.titlecase
# EXPECTED-EXCLUDE: helpers._normalise :: private_name


def _normalise(value: str) -> str:
    return value.strip().lower()


def slugify(value: str, separator: str = "-") -> str:
    return separator.join(_normalise(value).split())


def titlecase(value: str) -> str:
    return " ".join(word.capitalize() for word in value.split())
