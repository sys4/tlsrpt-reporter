#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import tlsrpt_reporter


class MyTestCase(unittest.TestCase):
    """
    tlsrpt-collectd must keep running when it receives a datagram it cannot use
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.socketname = os.path.join(self.tmpdir.name, "collectd.socket")
        config_file = os.path.join(self.tmpdir.name, "collectd.cfg")
        with open(config_file, "w") as f:
            f.write("[tlsrpt_collectd]\n")
            f.write("storage = sqlite://" + os.path.join(self.tmpdir.name, "collectd.sqlite") + "\n")
            f.write("socketname = " + self.socketname + "\n")
        # run the tlsrpt_reporter this test imported, not whatever is installed
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(tlsrpt_reporter.__file__)))
        self.proc = subprocess.Popen(
            [sys.executable, "-c", "from tlsrpt_reporter.tlsrpt import tlsrpt_collectd_main; tlsrpt_collectd_main()",
             "--config_file", config_file],
            cwd=self.tmpdir.name, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 10
        while not os.path.exists(self.socketname):
            if self.proc.poll() is not None or time.monotonic() > deadline:
                self.fail("collectd did not create its socket: " + self.proc.stderr.read().decode())
            time.sleep(0.05)

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc.stderr.close()
        self.tmpdir.cleanup()

    def test_invalid_datagrams(self):
        """
        Send datagrams that are not UTF-8, not JSON, or JSON but not an object
        """
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        for datagram in [b"\x80", b"x", b"1", b"null"]:
            sock.sendto(datagram, self.socketname)
        sock.close()
        time.sleep(1)
        if self.proc.poll() is not None:
            self.fail("collectd exited: " + self.proc.stderr.read().decode())

        self.proc.send_signal(signal.SIGTERM)
        self.assertEqual(self.proc.wait(timeout=10), 0)


if __name__ == '__main__':
    unittest.main()
