"""Meridian requirements mapper (stage 2).

Reads the stage-1 parser's ``ast.json`` and a requirements document and
produces two mapping artifacts. It is a separate program from the parser:
the two meet only through the ``ast.json`` file, never through imports (D8).
"""

__version__ = "0.1.0"

# The stage-1 envelope version this stage can read. Bumped only when the
# parser's output shape changes in a way the mapper must handle.
AST_SCHEMA_VERSION = 2
