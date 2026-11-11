"""Identifica a referência Linux usada por CLOCK_MONOTONIC."""
with open('/proc/sys/kernel/random/boot_id', encoding='ascii') as source:
    boot_id = source.read().strip()
with open('/proc/self/timens_offsets', encoding='ascii') as source:
    monotonic_offset = next(line.split()[1:] for line in source if line.split()[0] == 'monotonic')
CLOCK_ID = ':'.join([boot_id, *monotonic_offset])
