"""Flash history ACKs must fit one AES block so the LoRa gateway relays them as a single frame."""
import pytest

from wiot.domain.command_queue import CommandQueue, flash_request_limit
from wiot.domain.flash_archive import HISTORY_ACK, MAX_RECORDS
from wiot.protocol import messages_pb2 as pb
from wiot.protocol.transport import MqttNodeClient

KEY = bytes(range(16))


def ack_frame_len(node_id, request_id, phase=3, index=MAX_RECORDS):
    msg = pb.CMD_Message(node_id=node_id, cmd_id=HISTORY_ACK, cmd_data=(phase << 32) | index, request_id=request_id)
    return MqttNodeClient.encrypt_frame_static(msg.SerializeToString(), KEY)["frame_len"]


@pytest.mark.parametrize("node_id", [1, 2, 127, 128, 16383, 16384, 65535])
def test_worst_case_ack_is_one_block(node_id):
    limit = flash_request_limit(node_id)
    assert ack_frame_len(node_id, limit - 1) == 33          # version + IV + one block
    assert ack_frame_len(node_id, limit) == 49              # one more varint byte -> two blocks


def test_queue_allocates_small_ids_for_flash_commands_only(tmp_path):
    q = CommandQueue(tmp_path / "c.db")
    for i in range(40):
        r = q.enqueue("Company_1", 2, 12, "FLASH_TODAY", 0, delivery="now", now=1_800_000_000 + i)
        assert 1 <= r["request_id"] < flash_request_limit(2)
        q.enqueue("Company_1", 2, 13, "FLASH_CANCEL", 0, delivery="now", now=1_800_000_000 + i)
        if i % 8 == 7:                                     # keep the per-node window from filling
            q = CommandQueue(tmp_path / f"c{i}.db")
    other = CommandQueue(tmp_path / "v.db").enqueue("Company_1", 2, 4, "GOSTM", 0, delivery="now")["request_id"]
    assert 1 <= other <= 0xFFFFFFFF                        # non-flash commands keep the full 32-bit range
