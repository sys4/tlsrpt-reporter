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

# datagram, expected log message, whether it is saved to dump_path_for_invalid_datagram
INVALID_DATAGRAMS = [
    (b"\x80", "Malformed utf8 data received", True),
    (b"x", "JSON decode error", True),
    (b"1", "TypeError", False),
    (b"null", "TypeError", False),
]


class MyTestCase(unittest.TestCase):
    """
    tlsrpt-collectd must keep running when it receives a datagram it cannot use,
    log the incident and save the datagram if dump_path_for_invalid_datagram is configured
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.socketname = os.path.join(self.tmpdir.name, "collectd.socket")
        self.logfilename = os.path.join(self.tmpdir.name, "collectd.log")
        self.proc = None

    def tearDown(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait()
            self.proc.stderr.close()
        self.tmpdir.cleanup()

    def start_collectd(self, dump_path=None):
        config_file = os.path.join(self.tmpdir.name, "collectd.cfg")
        with open(config_file, "w") as f:
            f.write("[tlsrpt_collectd]\n")
            f.write("storage = sqlite://" + os.path.join(self.tmpdir.name, "collectd.sqlite") + "\n")
            f.write("socketname = " + self.socketname + "\n")
            f.write("logfilename = " + self.logfilename + "\n")
            if dump_path is not None:
                f.write("dump_path_for_invalid_datagram = " + dump_path + "\n")
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

    def read_log(self):
        try:
            with open(self.logfilename) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def send_and_wait_for_log(self, datagram, message):
        """
        Send a datagram and wait until collectd logs an error containing message
        :return: the new log lines
        """
        before = self.read_log()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.sendto(datagram, self.socketname)
        sock.close()
        deadline = time.monotonic() + 5
        while True:
            new_lines = self.read_log()[len(before):]
            for line in new_lines.splitlines():
                if message in line:
                    self.assertIn(" ERROR ", line)
                    return new_lines
            if self.proc.poll() is not None:
                self.fail("collectd exited: " + self.proc.stderr.read().decode())
            if time.monotonic() > deadline:
                self.fail("collectd did not log %r for datagram %r, log so far:\n%s" %
                          (message, datagram, self.read_log()))
            time.sleep(0.05)

    def assert_still_running_and_stop(self):
        if self.proc.poll() is not None:
            self.fail("collectd exited: " + self.proc.stderr.read().decode())
        self.proc.send_signal(signal.SIGTERM)
        self.assertEqual(self.proc.wait(timeout=10), 0)

    def test_invalid_datagrams_without_dump_path(self):
        """
        With the default configuration invalid datagrams are logged, nothing is saved
        """
        self.start_collectd()
        for datagram, message, _ in INVALID_DATAGRAMS:
            with self.subTest(datagram=datagram):
                new_lines = self.send_and_wait_for_log(datagram, message)
                self.assertNotIn("Could not save invalid datagram", new_lines)
        # only the files of the test setup, the log and the database
        for name in os.listdir(self.tmpdir.name):
            self.assertTrue(name.startswith("collectd."), name)
        self.assert_still_running_and_stop()

    def test_invalid_datagrams_are_saved(self):
        """
        Datagrams that are not UTF-8 or not JSON are logged and saved to dump_path_for_invalid_datagram
        """
        dump_path = os.path.join(self.tmpdir.name, "invalid.datagram")
        self.start_collectd(dump_path)
        for datagram, message, saved in INVALID_DATAGRAMS:
            with self.subTest(datagram=datagram):
                if os.path.exists(dump_path):
                    os.unlink(dump_path)
                new_lines = self.send_and_wait_for_log(datagram, message)
                if saved:
                    with open(dump_path, "rb") as f:
                        self.assertEqual(f.read(), datagram)
                else:
                    self.assertFalse(os.path.exists(dump_path))
        self.assert_still_running_and_stop()

    def test_dump_path_not_writable(self):
        """
        Failing to save an invalid datagram is logged and does not stop collectd
        """
        self.start_collectd(self.tmpdir.name)  # a directory cannot be written as a file
        for datagram, message, saved in INVALID_DATAGRAMS:
            if not saved:
                continue
            with self.subTest(datagram=datagram):
                new_lines = self.send_and_wait_for_log(datagram, "Could not save invalid datagram")
                self.assertIn(message, new_lines)
        self.assert_still_running_and_stop()


if __name__ == '__main__':
    unittest.main()
