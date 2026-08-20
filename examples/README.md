# Live Acceptance Examples

This directory contains small projects for a real live acceptance run.

## Fixtures

`fixtures/` contains three tiny Python projects with deliberate bugs. The
original fixture files are test inputs. Do not fix them in place.

- `boundary-bug/` has a boundary bug. The goal is to keep the final complete or
  short batch.
- `logic-bug/` has a logic bug. The goal is to calculate available inventory by
  subtracting reserved units.
- `missing-implementation/` has a missing implementation. The goal is to
  return a label in the documented format.

## Live acceptance script

`scripts/live_acceptance.py` copies each fixture to a temporary Workspace. It
calls real DeepSeek to complete the tool loop. It then runs `unittest`
independently to verify the result.

Run it from the repository root:

```bash
python examples/scripts/live_acceptance.py --api-key-file .key
```

`.key` contains one API key on one line. Git ignores this file.

The script removes a temporary Workspace after a successful fixture. If a
fixture fails, it preserves the Workspace and prints its path for inspection.
It makes one real acceptance attempt per fixture. It does not retry
automatically.
