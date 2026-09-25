"""PCAP / Network analysis smoke tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tforensic import pcap_analysis as pa


class PcapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        pa.close()

    def tearDown(self):
        pa.close()
        self.tmp.cleanup()

    def test_sample_open_list(self):
        path = pa.write_sample_pcap(self.root / "sample.pcap")
        self.assertTrue(pa.is_pcap_file(path))
        sess = pa.open_pcap(path)
        self.assertTrue(sess.packet_count and sess.packet_count >= 2)
        pkts = pa.packet_list(limit=10)
        self.assertGreaterEqual(pkts["returned"], 2)
        self.assertTrue(pkts["packets"][0]["src"])
        protos = pa.protocol_stats()
        self.assertTrue(protos)
        convs = pa.conversations(kind="ip")
        # tshark or native should see the 10.0.0.1 <-> 10.0.0.2 pair
        self.assertTrue(any("10.0.0" in (c["a"] + c["b"]) for c in convs) or sess.engine == "native")
        detail = pa.packet_detail(pkts["packets"][0]["no"])
        self.assertIn("tree", detail)
        summ = pa.summary()
        self.assertTrue(summ["open"])
        pa.close()
        self.assertFalse(pa.summary().get("open"))


if __name__ == "__main__":
    unittest.main()
