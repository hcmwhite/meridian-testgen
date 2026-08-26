"""Meridian unit-test generator (stage 3).

Reads the stage-2 mapper's two artifacts plus the codebase they describe and
generates pytest files, grouped by top-level requirement category. It is a
separate program from the parser and the mapper: the stages meet only through
artifact files, never through imports (D22).
"""

__version__ = "0.1.0"

# The stage-2 artifact envelope version this stage can read.
MAPPING_SCHEMA_VERSION = 1

ARTIFACT_MAPPING_AST = "mapping_ast"
ARTIFACT_MAPPING_REQUIREMENTS = "mapping_requirements"
