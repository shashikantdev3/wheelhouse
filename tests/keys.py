"""Approver keys shared by the tests."""

from wheelhouse.safety import ApprovalAuthority, ApproverKey

SHASHIKANT = ApproverKey.generate("shashikant")
OTHER = ApproverKey.generate("other")
LEDGER_KEY = b"k" * 32


def authority() -> ApprovalAuthority:
    return ApprovalAuthority({"shashikant": SHASHIKANT.public_key, "other": OTHER.public_key})
