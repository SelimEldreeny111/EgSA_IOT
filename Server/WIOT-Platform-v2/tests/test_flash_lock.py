"""One flash conversation per node (OI-04): a running download or an unanswered flash
command blocks further flash commands for that node; Cancel is always accepted."""
import time

import pytest

from wiot.domain.command_queue import ACK_TIMEOUT_SECONDS, CommandConflict, CommandQueue
from wiot.domain.flash_archive import TRANSFER_IDLE_S, FlashArchive
from wiot.protocol import messages_pb2 as pb

NOW = 1_800_000_000
API = "/api/v2"


def history(phase=2, index=1, total=5, request=91, result=0):
    msg = pb.Telemetry(node_id=2, timestamp=NOW - 300 + index, flow_rate=1.0,
                       sample_sequence=index, stored_sample=True, sample_time_valid=True)
    msg.history.CopyFrom(pb.HistoryInfo(request_id=request, generation=8, sequence=index if phase == 2 else 0,
                                        index=index, total=total, day_key=20261109, kind=2, phase=phase,
                                        result=result, ack_required=True))
    return msg


@pytest.fixture()
def journal(tmp_path):
    return CommandQueue(tmp_path / "journal.db")


def send(journal, cmd_type, cmd_id, node=2, now=NOW, company="Company_1"):
    r = journal.enqueue(company, node, cmd_id, cmd_type, 0, now=now, delivery="now")
    journal.claim_immediate(r["request_id"], now)
    return r["request_id"]


def test_unanswered_flash_command_blocks_the_next_one(journal):
    rid = send(journal, "FLASH_STATUS", 10)
    with pytest.raises(CommandConflict) as err:
        send(journal, "FLASH_LAST", 11, now=NOW + 5)
    assert err.value.blocking["request_id"] == rid and "FLASH_STATUS" in str(err.value)
    assert journal.active_flash("Company_1", 2, NOW + 5)["request_id"] == rid


def test_cancel_is_always_accepted(journal):
    send(journal, "FLASH_TODAY", 12)
    send(journal, "FLASH_CANCEL", 13, now=NOW + 1)          # does not raise


def test_lock_ends_on_reply_or_ack_timeout(journal):
    rid = send(journal, "FLASH_STATUS", 10)
    assert journal.acknowledge("Company_1", 2, rid, 10, now=NOW + 3)
    rid2 = send(journal, "FLASH_LAST", 11, now=NOW + 4)     # reply received: free again
    later = NOW + 4 + ACK_TIMEOUT_SECONDS + 1                # no reply: freed by the ACK timeout
    assert journal.active_flash("Company_1", 2, later) is None
    send(journal, "FLASH_STATUS", 10, now=later)
    assert rid2 != rid


def test_lock_is_per_node_and_per_company_and_ignores_other_commands(journal):
    send(journal, "FLASH_STATUS", 10)
    send(journal, "FLASH_STATUS", 10, node=3)
    send(journal, "FLASH_STATUS", 10, company="Company_2")
    journal.enqueue("Company_1", 2, 4, "GOSTM", 0, now=NOW, delivery="next_wake")   # not a flash command


def test_running_download_is_active_until_end_or_idle(tmp_path):
    archive = FlashArchive(tmp_path / "flash.db")
    archive.accept("Company_1", "Region_1", 2, history(index=1), now=NOW)
    t = archive.active_transfer("Company_1", "Region_1", 2, now=NOW + 60)
    assert t["request"] == 91 and t["received"] == 1 and t["total"] == 5
    assert archive.active_transfer("Company_1", "Region_1", 2, now=NOW + TRANSFER_IDLE_S + 1) is None
    assert archive.active_transfer("Company_1", "Region_1", 3, now=NOW + 60) is None
    archive.accept("Company_1", "Region_1", 2, history(phase=3, index=5, result=4), now=NOW + 90)  # cancelled
    assert archive.active_transfer("Company_1", "Region_1", 2, now=NOW + 91) is None


def test_rejected_download_is_not_active(tmp_path):
    archive = FlashArchive(tmp_path / "flash.db")
    archive.accept("Company_1", "Region_1", 2, history(phase=1, index=0, total=0, result=8), now=NOW)  # Busy
    assert archive.active_transfer("Company_1", "Region_1", 2, now=NOW + 1) is None


# ------------------------------------------------------------------- HTTP API
def test_api_refuses_second_flash_command_with_409(supervisor):
    q = {"company": "Company_1", "node_id": 2, "delivery": "next_wake"}
    first = supervisor.post(f"{API}/commands", json={**q, "cmd_type": "FLASH_STATUS"})
    assert first.status_code == 202, first.text
    second = supervisor.post(f"{API}/commands", json={**q, "cmd_type": "FLASH_LAST"})
    assert second.status_code == 409
    body = second.json()
    assert body["lock"]["kind"] == "queued" and body["lock"]["request_id"] == first.json()["request_id"]
    assert supervisor.post(f"{API}/commands", json={**q, "cmd_type": "FLASH_CANCEL"}).status_code == 202
    lock = supervisor.get(f"{API}/flash/lock", params={"company": "Company_1", "node_id": 2}).json()["lock"]
    assert lock["cmd_type"] == "FLASH_CANCEL"                # the newest unfinished flash command
    assert supervisor.get(f"{API}/flash/lock", params={"company": "Company_1", "node_id": 9}).json()["lock"] is None


def test_api_refuses_flash_commands_during_a_download(supervisor, app):
    now = int(time.time())
    app.state.runtime.ingest.flash.accept("Company_1", "Region_1", 2, history(index=1), now=now)
    r = supervisor.post(f"{API}/commands", json={"company": "Company_1", "node_id": 2, "cmd_type": "CLEAR_FLASH",
                                                  "delivery": "next_wake"})
    assert r.status_code == 409 and r.json()["lock"]["kind"] == "download"
    assert "#91" in r.json()["detail"]
    analysis = supervisor.get(f"{API}/flash/analysis", params={"company": "Company_1", "node_id": 2}).json()
    assert analysis["lock"]["received"] == 1 and analysis["lock"]["total"] == 5
