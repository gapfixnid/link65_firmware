"""Deterministic synthetic inputs; no captured user settings or device access."""
PHYSICAL = [r * 15 + c for r in range(5) for c in range(15)
            if (r, c) not in {(2, 12), (3, 12), (4, 3), (4, 5), (4, 6), (4, 9), (4, 10), (4, 11)}]

def scenarios():
    cases = {
        'clean': [(10000, 0, 1), (50000, 0, 0)],
        'press_and_release_bounce': [(10000, 0, 1), (11000, 0, 0), (12000, 0, 1),
                                     (13000, 0, 0), (14000, 0, 1), (50000, 0, 0),
                                     (51000, 0, 1), (52000, 0, 0)],
        'one_ms_spike': [(10000, 0, 1), (11000, 0, 0)],
        'four_ms_spike': [(10000, 0, 1), (14000, 0, 0)],
        'two_keys_4ms_apart': [(10000, 0, 1), (14000, 1, 1), (50000, 0, 0), (50000, 1, 0)],
        'other_key_noise': [(10000, 0, 1)] + [(t, 1, int(i % 2 == 0)) for i, t in enumerate(range(10000, 42000, 2000))]
                           + [(60000, 0, 0)],
        '67_key_chord': [(10000, k, 1) for k in PHYSICAL] + [(80000, k, 0) for k in PHYSICAL],
        '67_key_roll': [(10000 + 500 * i, k, 1) for i, k in enumerate(PHYSICAL)] + [(80000, k, 0) for k in PHYSICAL],
        'three_ms_tap': [(10000, 0, 1), (13000, 0, 0)],
        'three_ms_repress_gap': [(10000, 0, 1), (20000, 0, 0), (23000, 0, 1), (40000, 0, 0)],
        'late_press_bounce': [(10000, 0, 1), (16000, 0, 0), (17000, 0, 1), (50000, 0, 0)],
        'one_ms_release_glitch': [(10000, 0, 1), (30000, 0, 0), (31000, 0, 1), (60000, 0, 0)],
        'both_edges_at_5ms': [(10000, 0, 1), (15000, 0, 0)],
    }
    return {name: sorted(events) for name, events in cases.items()}
