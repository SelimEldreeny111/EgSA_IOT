"""Fail-closed validation for the existing V1 wire/API contract (no schema change)."""
import math
import re

SQLITE_MAX_INT = 2**63 - 1
MAX_EPOCH = 253402300799  # Last second representable in year 9999.
MAX_PROTO_BYTES = 4096   # Well above current nanopb frames; bounds hostile input.


def company_id(value):
    """Company topic IDs are immutable identifiers, not filesystem names or rooms."""
    if (not isinstance(value, str) or value == '__all__' or
            not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9 _-]{0,79}', value) or
            value != value.strip()):
        raise ValueError('Invalid company ID: use 1..80 ASCII letters, digits, spaces, _ or -')
    return value


def integer(value, minimum, maximum, label):
    """Accept whole ASCII decimal strings or ints, never bools/floats/coercion."""
    if isinstance(value, bool) or not (isinstance(value, int) or
            isinstance(value, str) and re.fullmatch(r'[0-9]+', value.strip())):
        raise ValueError(f'{label} must be a whole number')
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError(f'{label} must be {minimum}..{maximum}')
    return result


def parse_topic(topic):
    """Return (company, region, node, kind), with data decoded as Telemetry."""
    from region_topics import region_id
    if not isinstance(topic, str) or len(topic) > 256:
        raise ValueError('Invalid MQTT topic')
    parts = topic.split('/')
    if len(parts) not in (4, 5) or parts[0] != 'wiot':
        raise ValueError('Expected wiot/company/region/node/data|status|cmd or region/broadcast')
    company, region = company_id(parts[1]), region_id(parts[2])
    if len(parts) == 4:
        if parts[3] != 'broadcast':
            raise ValueError('Unsupported regional broadcast topic')
        return company, region, 0, 'cmd'
    if parts[4] not in ('data', 'status', 'cmd'):
        raise ValueError('Unsupported lowercase topic suffix')
    if not re.fullmatch(r'[1-9][0-9]{0,4}', parts[3]):
        raise ValueError('Invalid topic node ID')
    return company, region, integer(parts[3], 1, 65535, 'Node ID'), ('telemetry' if parts[4] == 'data' else parts[4])


def validate_message(message, topic_node):
    """Validate before any storage, live emission, mailbox ACK or dispatch.

    Zero-valued omitted legacy fields remain valid. Reverse instantaneous flow
    and signed net totals are intentional; installation limits are not guessed.
    Unknown appended protobuf fields remain compatible. Known enums fail closed.
    """
    broadcast_echo = message.DESCRIPTOR.name == 'CMD_Message' and topic_node == 0
    if broadcast_echo:
        integer(message.node_id, 0, 65535, 'Broadcast payload node ID')
    elif message.node_id != topic_node:
        raise ValueError(f'Node ID mismatch - topic={topic_node}, payload={message.node_id}')
    if message.DESCRIPTOR.name == 'CMD_Message':
        integer(message.cmd_id, 1, 8, 'Command ID')
        integer(message.cmd_data, 0, SQLITE_MAX_INT, 'Command data')
        if message.cmd_id in (7, 8) and (broadcast_echo or message.cmd_data != 0 or not message.request_id):
            raise ValueError('Counter clear requires direct node, data=0 and request ID')
        return
    for descriptor in message.DESCRIPTOR.fields:
        value = getattr(message, descriptor.name)
        if descriptor.type == descriptor.TYPE_MESSAGE:
            if message.HasField(descriptor.name):
                _validate_reading(value)
        elif descriptor.type in (descriptor.TYPE_FLOAT, descriptor.TYPE_DOUBLE):
            if not math.isfinite(value):
                raise ValueError(f'{descriptor.name} must be finite')
        elif descriptor.type == descriptor.TYPE_UINT64 and value > SQLITE_MAX_INT:
            raise ValueError(f'{descriptor.name} exceeds durable integer range')
    _validate_reading(message)
    integer(message.timestamp, 0, MAX_EPOCH, 'Timestamp')
    for field, maximum in (('node_status', 3), ('active_sensor_count', 4),
            ('sensor_mask', 15), ('soil_moisture_temp_valid', 1),
            ('soil_moisture_temp_ec_valid', 1), ('power_mode', 5), ('power_state', 2)):
        integer(getattr(message, field), 0, maximum, field)
    if message.DESCRIPTOR.name == 'Telemetry':
        for field in ('sampling_rate', 'Transmission_rate'):
            value = getattr(message, field)
            # The CMD data is seconds, but CommandHandler reports its internal
            # periods in milliseconds. Do not reject valid long report intervals.
            if value and not 5000 <= value <= 86400000:
                raise ValueError(f'{field} must be 0 (legacy) or 5000..86400000 milliseconds')
        integer(message.command_ack_cmd_id, 0, 8, 'ACK command ID')


def _validate_reading(reading):
    for descriptor in reading.DESCRIPTOR.fields:
        value = getattr(reading, descriptor.name)
        if descriptor.type in (descriptor.TYPE_FLOAT, descriptor.TYPE_DOUBLE) and not math.isfinite(value):
            raise ValueError(f'{descriptor.name} must be finite')
        if descriptor.type == descriptor.TYPE_UINT64 and value > SQLITE_MAX_INT:
            raise ValueError(f'{descriptor.name} exceeds durable integer range')
    for field, maximum in (('flow_meter_type', 2), ('flow_period_source', 2),
            ('flow_period_quality', 6)):
        integer(getattr(reading, field), 0, maximum, field)
