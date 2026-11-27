"""Exercise the real React/FastAPI stack in headless Chrome with seeded test data."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"
API = "http://127.0.0.1:18118"
UI = "http://127.0.0.1:15173"
CASE_ID = "2026-PUN-0219"


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def clean_test_data(directory):
    for attempt in range(5):
        try:
            directory.cleanup()
            return
        except OSError as exc:
            # Windows can briefly retain a server log handle after the child exits.
            if getattr(exc, "winerror", None) not in (32, 267) or attempt == 4:
                raise
            time.sleep(0.5)


def start(stack, command, directory, env, log_path):
    # Logs remain available during startup checks without blocking either child on a pipe.
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT)
    stack.callback(stop, process)
    return process


def wait_for_server(process, url, log_path):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, OSError):
            time.sleep(0.2)
    raise RuntimeError(f"Server did not start at {url}\n{log_path.read_text(errors='replace')}")


def run_browser_tests():
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    class BrowserTests(unittest.TestCase):
        def setUp(self):
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1440,1000")
            self.driver = webdriver.Chrome(options=options)
            self.addCleanup(self.driver.quit)
            self.driver.set_page_load_timeout(30)
            # React renders after HTTP responses, so wait for the expected UI state.
            self.wait = WebDriverWait(self.driver, 12)
            self.driver.get(UI)

        def visible(self, selector):
            return self.wait.until(ec.visibility_of_element_located((By.CSS_SELECTOR, selector)))

        def click(self, by, selector):
            self.wait.until(ec.element_to_be_clickable((by, selector))).click()

        def enter_directory(self):
            self.assertEqual(self.visible(".login h1").text, "Investigator sign-in")
            self.click(By.CSS_SELECTOR, ".login button[type=submit]")
            return self.visible(f'.case-card[href="#/case/{CASE_ID}"]')

        def open_case(self):
            self.enter_directory().click()
            self.assertEqual(self.visible(".case-file .eyebrow").text.upper(), f"CASE {CASE_ID}")

        def test_demo_entry_lists_seeded_case(self):
            card = self.enter_directory()
            self.assertIn("Shree Lakshmi Jewellers theft", card.text)
            self.assertEqual(self.visible(".directory h1").text, "Cases")

        def test_open_and_close_evidence_details(self):
            self.open_case()
            card = self.visible('.case-file .ecard[role="button"]')
            label = card.get_dom_attribute("aria-label")
            # The layered buttons overlap at their centers, so activate the native button by keyboard.
            ActionChains(self.driver).move_to_element(card).perform()
            self.visible('.case-file .ecard button[aria-label="View record"]').send_keys(Keys.SPACE)
            dialog = self.visible('.evidence-modal[role="dialog"]')
            self.assertTrue(label.startswith(dialog.get_dom_attribute("aria-label")))
            self.click(By.CSS_SELECTOR, '.evidence-modal button[aria-label="Close"]')
            self.wait.until(ec.invisibility_of_element_located((By.CSS_SELECTOR, ".evidence-modal")))

        def test_start_interview_discard_draft_and_end_interview(self):
            self.open_case()
            self.click(By.XPATH, '//li[.//strong[text()="Suresh Deshmukh"]]/button[text()="Interview"]')
            self.assertEqual(self.visible(".stage-head .who b").text, "Suresh Deshmukh")
            self.click(By.XPATH, '//button[text()="Type instead"]')
            draft = self.visible('textarea[aria-label="Statement to send"]')
            send = self.driver.find_element(By.XPATH, '//button[text()="Send"]')
            self.assertFalse(send.is_enabled())
            draft.send_keys("Selenium draft for this test only.")
            self.assertTrue(send.is_enabled())
            self.click(By.XPATH, '//button[text()="Discard"]')
            self.wait.until(ec.staleness_of(draft))
            self.click(By.XPATH, '//button[text()="End interview"]')
            self.click(By.XPATH, '//*[@role="dialog"]//button[text()="End interview"]')
            self.assertEqual(self.visible(".stage-controls.ended p").text, "Interview ended.")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BrowserTests)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def main():
    node = shutil.which("node")
    vite = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.is_file():
        print("Install Node.js and run npm ci from frontend before running Selenium.", file=sys.stderr)
        return 2

    try:
        from selenium import webdriver  # Check before starting either server.
    except ImportError:
        print("Install Selenium with: python -m pip install selenium", file=sys.stderr)
        return 2

    try:
        # Fail early if a server is already there so tests cannot mutate its data.
        for port in (18118, 15173):
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", port))
        with ExitStack() as stack:
            directory = tempfile.TemporaryDirectory(prefix="veritas-selenium-")
            stack.callback(clean_test_data, directory)
            data = Path(directory.name)
            # Browser actions mutate interviews. Seed a fresh database for this run only.
            env = dict(os.environ, VERITAS_DB=str(data / "test.db"),
                       VERITAS_UPLOADS=str(data / "uploads"), VITE_API_URL=API)
            # The CLI also warms the live route cache. These browser flows only need the records.
            subprocess.run([sys.executable, "-c", "from seed import seed; seed()"],
                           cwd=BACKEND, env=env, check=True, timeout=30)
            api_log = data / "api.log"
            api = start(stack, [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                                "--port", "18118"], BACKEND, env, api_log)
            wait_for_server(api, f"{API}/cases/{CASE_ID}", api_log)
            ui_log = data / "ui.log"
            ui = start(stack, [node, str(vite), "--host", "127.0.0.1", "--port", "15173", "--strictPort"],
                       FRONTEND, env, ui_log)
            wait_for_server(ui, UI, ui_log)
            return run_browser_tests()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Selenium setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
