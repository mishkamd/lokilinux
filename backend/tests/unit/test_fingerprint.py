from lokilinux.events.fingerprint import fingerprint


def test_deterministic_for_same_inputs():
    a = fingerprint("default", "host-1", "cpu.high", None)
    b = fingerprint("default", "host-1", "cpu.high", None)
    assert a == b


def test_distinct_tenants_never_collide():
    a = fingerprint("tenant-a", "host-1", "cpu.high", None)
    b = fingerprint("tenant-b", "host-1", "cpu.high", None)
    assert a != b


def test_distinct_types_never_collide():
    a = fingerprint("default", "host-1", "cpu.high", None)
    b = fingerprint("default", "host-1", "memory.high", None)
    assert a != b


def test_resource_defaults_to_host_id():
    a = fingerprint("default", "host-1", "cpu.high", None)
    b = fingerprint("default", "host-1", "cpu.high", "host-1")
    assert a == b


def test_explicit_resource_overrides_host_id():
    a = fingerprint("default", "host-1", "job.failed", "job-42")
    b = fingerprint("default", "host-1", "job.failed", "job-43")
    assert a != b


def test_is_a_32_char_hex_string():
    fp = fingerprint("default", "host-1", "cpu.high", None)
    assert len(fp) == 32
    int(fp, 16)  # raises ValueError if not hex
