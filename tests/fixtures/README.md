# Fixtures

Every fixture here is synthetic. The status messages are built from the message
assembly in the reactive Magpie charm's `check_nodes()`, so the grammar the
parser is tested against is pinned in this repository rather than remembered.

## Adding a capture from a real deployment

A real `juju status --format json` and its `iperf.csv` are the most valuable
fixtures available, and the ones that cannot be committed as they are. They carry
customer-identifying data:

- machine and unit hostnames
- IP addresses, in the status document and in every CSV row
- MAC addresses, in the CSV
- interface names, which can identify a hardware platform
- the model name and, often, the project name in surrounding paths

Anonymize a capture by hand before adding it, and have a second person confirm
the result. Do not automate this: a substitution that misses one field publishes
it permanently in git history.

When anonymizing, keep the structure that makes the fixture worth having:

- preserve the unit-to-machine mapping exactly, including its permutation, since
  that is what most of the parsing tests exercise
- preserve the relative throughput values, since the diagnosis rules compare
  against a peer median rather than against absolute numbers
- preserve the required MTU per space
- keep interface classes distinguishable, for example a bond against a single NIC,
  because the throughput rules depend on that distinction

`test_reporting.py` asserts that no committed fixture renders non-ASCII output,
but nothing in the suite can detect a hostname that was left behind. That check
is yours.
