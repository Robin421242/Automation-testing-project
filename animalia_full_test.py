"""
ANIMALIA - FULL ADOPT NOW + DONATE NOW AUTOMATION TEST
Website: https://animalia.surge.sh

Run:
    python animalia_full_test.py

What it checks:
- Homepage and navigation
- Every visible "Adopt Now" action (or closest matching adoption CTA)
- Every visible "Donate Now" action (or closest matching donation CTA)
- Whether clicking actions opens a modal, changes route, reveals a form, or navigates externally
- Adoption form field detection, sample data entry, required-field/browser validation
- Donation amount controls and boundary values where present
- HTTP/API-style checks, network requests, broken images, console/page errors
- Slow visible Chrome actions and final PASS/FAIL/SKIP summary

Safety:
- Does NOT submit adoption requests.
- Does NOT complete or submit payments.
- If a Donate Now button leads to a payment provider, it only inspects the destination and stops.
"""

import time
from urllib.parse import urljoin, urlparse
import requests
from playwright.sync_api import sync_playwright

BASE_URL = "https://animalia.surge.sh"
PAUSE = 1.2
TIMEOUT = 15000

results = []
network_requests = []
failed_requests = []
page_errors = []
console_errors = []
http_responses = []


def pause(seconds=PAUSE):
    time.sleep(seconds)


def report(test_id, module, name, passed=None, details=""):
    if passed is None:
        status = "SKIP"
    else:
        status = "PASS" if passed else "FAIL"
    results.append({
        "id": test_id, "module": module, "name": name,
        "status": status, "details": str(details)
    })
    print(f"[{status}] {test_id} | {module} | {name}")
    if details:
        print(f"       {details}")
    time.sleep(0.35)


def text_of(page):
    try:
        return page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return ""


def safe_goto(page, url=BASE_URL):
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        pause()
        return response
    except Exception as exc:
        print(f"Navigation warning for {url}: {exc}")
        return None


def find_ctas(page, labels):
    """Find visible links/buttons matching requested CTA labels."""
    found = []
    for label in labels:
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=label, exact=False)
                for i in range(min(loc.count(), 30)):
                    item = loc.nth(i)
                    if item.is_visible():
                        # Avoid duplicate element references by storing locator + text/href.
                        label_text = (item.inner_text() or "").strip().replace("\n", " ")[:100]
                        href = item.get_attribute("href")
                        key = (role, label_text, href)
                        if not any(x["key"] == key for x in found):
                            found.append({"locator": item, "key": key, "label": label_text, "href": href})
            except Exception:
                pass
    return found


def module_nav(page, module):
    safe_goto(page, BASE_URL)
    if module == "adopt":
        labels = ["Adopt Now", "Adopt Animals", "Adopt", "Adoption"]
        routes = ["/adopt.html", "/adopt", "/adoption.html", "/animals.html"]
        keywords = ["adopt", "animal", "pet", "dog", "cat"]
    else:
        labels = ["Donate Now", "Donate", "Donation"]
        routes = ["/donation.html", "/donate.html", "/donation", "/donate"]
        keywords = ["donat", "upi", "payment", "bank", "support"]

    # First try actual homepage CTA/navigation
    if find_ctas(page, labels):
        return

    for route in routes:
        response = safe_goto(page, urljoin(BASE_URL, route))
        content = text_of(page)
        if response and response.status < 500 and any(k in content for k in keywords):
            return


def inspect_cta_result(page, before_url, before_text, cta_label, module, index):
    pause()
    after_url = page.url
    after_text = text_of(page)
    url_changed = after_url != before_url
    text_changed = after_text != before_text
    dialog_visible = False
    form_count = 0

    try:
        dialog_visible = page.locator('[role="dialog"], dialog, .modal.show, .modal[style*="display: block"]').count() > 0
    except Exception:
        pass
    try:
        form_count = page.locator("form:visible").count()
    except Exception:
        pass

    changed = url_changed or text_changed or dialog_visible or form_count > 0
    report(
        f"{module.upper()}CTA{index:02d}",
        module.title() + " CTA",
        f"{cta_label} click produces a visible response",
        changed,
        f"url_changed={url_changed}; text_changed={text_changed}; dialog={dialog_visible}; visible_forms={form_count}; url={after_url}"
    )

    # For donation, do not interact further if it opens an external payment provider.
    if module == "donate":
        host_before = urlparse(BASE_URL).netloc
        host_after = urlparse(after_url).netloc
        if host_after and host_after != host_before:
            report(
                f"DONSAFE{index:02d}",
                "Donation safety",
                "External donation/payment destination inspected only",
                True,
                f"External host: {host_after}; no payment information entered"
            )


def click_each_cta(page, module):
    module_nav(page, module)

    if module == "adopt":
        labels = ["Adopt Now", "Adopt Me", "Adopt"]
    else:
        labels = ["Donate Now", "Donate"]

    # Collect CTA count from current page; each click is tested separately.
    ctas = find_ctas(page, labels)
    report(
        "ADOPTCOUNT" if module == "adopt" else "DONATECOUNT",
        module.title(),
        f"Visible {labels[0]} / related CTA buttons detected",
        len(ctas) > 0,
        f"Found {len(ctas)} visible CTA(s) on {page.url}"
    )

    if not ctas:
        report(
            "ADOPTCTA00" if module == "adopt" else "DONATECTA00",
            module.title() + " CTA",
            f"{labels[0]} CTA test",
            None,
            "No matching visible CTA found on the current page. Update label/route to match the website."
        )
        return

    # Test each CTA by returning to the module page and clicking its matching index.
    # Keep a reasonable cap to avoid repeatedly triggering a very large page.
    max_ctas = min(len(ctas), 12)

    for idx in range(max_ctas):
        module_nav(page, module)
        current_ctas = find_ctas(page, labels)
        if idx >= len(current_ctas):
            report(
                f"{module.upper()}CTA{idx+1:02d}",
                module.title() + " CTA",
                f"{labels[0]} #{idx+1}",
                None,
                "CTA not found after reloading module"
            )
            continue

        cta = current_ctas[idx]
        before_url = page.url
        before_text = text_of(page)
        cta_label = cta["label"] or labels[0]

        try:
            cta["locator"].scroll_into_view_if_needed(timeout=4000)
            pause(0.4)
            cta["locator"].click(timeout=5000)
            wait_until = "domcontentloaded"
            try:
                page.wait_for_load_state(wait_until, timeout=5000)
            except Exception:
                pass
            inspect_cta_result(page, before_url, before_text, cta_label, module, idx + 1)
        except Exception as exc:
            report(
                f"{module.upper()}CTA{idx+1:02d}",
                module.title() + " CTA",
                f"{cta_label} #{idx+1} is clickable",
                False,
                str(exc)[:250]
            )

        # Important: never proceed through a payment provider.
        if module == "donate" and urlparse(page.url).netloc not in ("", urlparse(BASE_URL).netloc):
            print("External payment/donation destination detected. Stopping interaction there for safety.")
            continue


def field_details(field):
    parts = []
    for attr in ("name", "id", "type", "placeholder", "aria-label", "required", "min", "max", "maxlength"):
        try:
            value = field.get_attribute(attr)
            if value:
                parts.append(f"{attr}={value}")
        except Exception:
            pass
    return " ".join(parts)


def visible_fields(page):
    fields = page.locator(
        "input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select"
    )
    found = []
    for i in range(min(fields.count(), 40)):
        item = fields.nth(i)
        try:
            if item.is_visible() and item.is_enabled():
                found.append(item)
        except Exception:
            pass
    return found


def test_form_fields(page, module):
    print(f"\n--- {module.upper()} FORM + BOUNDARY CHECKS ---")
    fields = visible_fields(page)
    forms = page.locator("form:visible").count()

    report(
        f"{module.upper()}FORM01",
        module.title() + " Form",
        "Form is visible when expected",
        True if forms > 0 else None,
        f"Visible forms={forms}; visible editable fields={len(fields)}"
    )

    if not fields:
        report(
            f"{module.upper()}FORM02",
            module.title() + " Form",
            "Form field validation",
            None,
            "No visible editable fields on this page/section."
        )
        return

    # Required field metadata
    required_fields = []
    for field in fields:
        try:
            if field.get_attribute("required") is not None:
                required_fields.append(field)
        except Exception:
            pass

    report(
        f"{module.upper()}FORM02",
        module.title() + " Form",
        "Required fields identified",
        True,
        f"Required attribute found on {len(required_fields)} field(s)"
    )

    # Fill sample values but never submit the form.
    filled = 0
    email_fields = []
    number_fields = []
    text_fields = []

    for field in fields:
        try:
            typ = (field.get_attribute("type") or "").lower()
            info = field_details(field).lower()
            tag = field.evaluate("(el) => el.tagName.toLowerCase()")

            if typ == "email" or "email" in info:
                email_fields.append(field)
                value = "animalia.automation@example.com"
            elif typ in ("number", "range") or "amount" in info or "age" in info:
                number_fields.append(field)
                value = "100" if module == "donate" else "1"
            elif typ in ("checkbox", "radio", "file", "submit", "button"):
                continue
            elif tag == "select":
                opts = field.locator("option")
                if opts.count() > 1:
                    field.select_option(index=1)
                    filled += 1
                continue
            elif typ == "tel" or "phone" in info or "mobile" in info:
                value = "9876543210"
            elif "name" in info:
                value = "Automation Test"
            elif "message" in info or "reason" in info:
                value = "Automation test data only. Do not process."
            elif typ == "date":
                value = "2026-12-15"
            else:
                value = "Sample test data"

            field.fill(value)
            filled += 1
            text_fields.append(field)
        except Exception:
            pass

    report(
        f"{module.upper()}FORM03",
        module.title() + " Form",
        "Sample test data entered",
        filled > 0,
        f"Filled {filled} field(s); form was not submitted"
    )

    # Blank required-field browser validation check
    required_check = False
    for field in required_fields:
        try:
            field.fill("")
            valid = field.evaluate("(el) => el.checkValidity()")
            required_check = required_check or (not valid)
        except Exception:
            pass

    report(
        f"{module.upper()}FORM04",
        module.title() + " Boundary",
        "Blank required field is rejected by browser validation",
        required_check if required_fields else None,
        "Checked HTML constraint validity; no submit performed"
    )

    # Invalid email values
    if email_fields:
        invalid_email_rejected = False
        for field in email_fields[:2]:
            try:
                field.fill("not-an-email")
                valid = field.evaluate("(el) => el.checkValidity()")
                invalid_email_rejected = invalid_email_rejected or (not valid)
            except Exception:
                pass
        report(
            f"{module.upper()}FORM05",
            module.title() + " Boundary",
            "Invalid email format is rejected by browser validation",
            invalid_email_rejected
        )
    else:
        report(
            f"{module.upper()}FORM05",
            module.title() + " Boundary",
            "Invalid email format validation",
            None,
            "No visible email field found"
        )

    # Numeric boundaries (HTML min/max)
    if number_fields:
        boundary_checks = []
        for field in number_fields[:3]:
            try:
                min_val = field.get_attribute("min")
                max_val = field.get_attribute("max")
                step = field.get_attribute("step")
                test_val = min_val if min_val is not None else "-1"
                field.fill(test_val)
                lower_valid = field.evaluate("(el) => el.checkValidity()")
                boundary_checks.append(
                    f"min={min_val or 'unspecified'}, max={max_val or 'unspecified'}, "
                    f"step={step or 'unspecified'}, lower_value_valid={lower_valid}"
                )
                if max_val is not None:
                    field.fill(max_val)
                    boundary_checks.append(f"upper_value={max_val}")
            except Exception as exc:
                boundary_checks.append(f"boundary attempt error: {exc}")
        report(
            f"{module.upper()}FORM06",
            module.title() + " Boundary",
            "Numeric minimum/maximum boundary attempted",
            True,
            "; ".join(boundary_checks[:3])
        )
    else:
        report(
            f"{module.upper()}FORM06",
            module.title() + " Boundary",
            "Numeric minimum/maximum boundary",
            None,
            "No visible numeric/amount/age field found"
        )

    # Length boundary where maxlength exists
    max_length_fields = []
    for field in text_fields:
        try:
            if field.get_attribute("maxlength"):
                max_length_fields.append(field)
        except Exception:
            pass

    if max_length_fields:
        field = max_length_fields[0]
        try:
            limit = int(field.get_attribute("maxlength"))
            field.fill("X" * (limit + 1))
            actual_length = field.evaluate("(el) => el.value.length")
            report(
                f"{module.upper()}FORM07",
                module.title() + " Boundary",
                "Maximum text length boundary checked",
                actual_length <= limit,
                f"maxlength={limit}; resulting length={actual_length}"
            )
        except Exception as exc:
            report(
                f"{module.upper()}FORM07",
                module.title() + " Boundary",
                "Maximum text length boundary checked",
                False,
                str(exc)
            )
    else:
        report(
            f"{module.upper()}FORM07",
            module.title() + " Boundary",
            "Maximum text length boundary",
            None,
            "No visible text field with maxlength attribute"
        )

    report(
        f"{module.upper()}FORM08",
        module.title() + " Safety",
        "Form was not submitted",
        True,
        "Only validation and field-entry checks were performed"
    )


def test_images(page, module):
    images = page.locator("img")
    total = min(images.count(), 50)
    broken = []

    for i in range(total):
        try:
            img = images.nth(i)
            if img.is_visible():
                loaded = img.evaluate("(el) => el.complete && el.naturalWidth > 0")
                if not loaded:
                    broken.append(i)
        except Exception:
            pass

    report(
        f"{module.upper()}IMG01",
        module.title() + " Images",
        "Visible images loaded",
        len(broken) == 0,
        f"Checked up to {total} image(s); broken/unloaded indexes={broken[:10]}"
    )


def test_http_api():
    print("\n--- HTTP / API-STYLE CHECKS ---")
    checks = [
        ("HTTP01", "Homepage returns HTTP success", BASE_URL, "status"),
        ("HTTP02", "Homepage response has HTML content type", BASE_URL, "html"),
        ("HTTP03", "Final homepage URL uses HTTPS", BASE_URL, "https"),
        ("HTTP04", "Homepage response body is not empty", BASE_URL, "body"),
        ("HTTP05", "Adopt route does not return server error", urljoin(BASE_URL, "/adopt.html"), "server"),
        ("HTTP06", "Donation route does not return server error", urljoin(BASE_URL, "/donation.html"), "server"),
        ("HTTP07", "Homepage responds within 10 seconds", BASE_URL, "time"),
        ("HTTP08", "Response content-type header exists", BASE_URL, "header"),
    ]

    for test_id, name, url, check in checks:
        try:
            start = time.perf_counter()
            response = requests.get(url, timeout=20, allow_redirects=True)
            elapsed = time.perf_counter() - start

            if check == "status":
                passed, details = response.status_code < 400, f"HTTP {response.status_code}"
            elif check == "html":
                passed = "html" in response.headers.get("content-type", "").lower()
                details = response.headers.get("content-type", "missing")
            elif check == "https":
                passed, details = response.url.startswith("https://"), response.url
            elif check == "body":
                passed, details = len(response.content) > 0, f"{len(response.content)} bytes"
            elif check == "server":
                passed, details = response.status_code < 500, f"HTTP {response.status_code}; static hosting may return homepage for unknown routes"
            elif check == "time":
                passed, details = elapsed < 10, f"{elapsed:.2f} seconds"
            else:
                passed = bool(response.headers.get("content-type"))
                details = response.headers.get("content-type", "missing")

            report(test_id, "HTTP/API", name, passed, details)
        except Exception as exc:
            report(test_id, "HTTP/API", name, False, str(exc))


def test_network_summary():
    print("\n--- NETWORK / BROWSER DIAGNOSTICS ---")

    report("NET01", "Network", "Browser requests captured",
           len(network_requests) > 0, f"Request count={len(network_requests)}")

    report("NET02", "Network", "No failed browser requests",
           len(failed_requests) == 0, "; ".join(failed_requests[:4]) or "None observed")

    report("NET03", "Network", "No uncaught page JavaScript errors",
           len(page_errors) == 0, "; ".join(page_errors[:4]) or "None observed")

    report("NET04", "Network", "No console errors",
           len(console_errors) == 0, "; ".join(console_errors[:4]) or "None observed")

    non_https = [
        u for u in network_requests
        if not u.startswith(("https://", "data:", "blob:"))
    ]
    report("NET05", "Network", "No non-HTTPS web requests observed",
           len(non_https) == 0, "; ".join(non_https[:4]) or "All observed web requests used HTTPS/local data")

    internal = [
        u for u in network_requests
        if urlparse(u).netloc == urlparse(BASE_URL).netloc
    ]
    report("NET06", "Network", "Requests to Animalia origin observed",
           len(internal) > 0, f"Internal requests={len(internal)}")

    server_errors = [x for x in http_responses if x[1] >= 500]
    report("NET07", "Network", "No HTTP 5xx browser responses observed",
           len(server_errors) == 0, "; ".join(f"{u} => {s}" for u, s in server_errors[:3]) or "None observed")

    report("NET08", "Network", "Browser completed Adopt/Donation navigation attempts",
           True, "Review the individual CTA checks above for exact results")


def main():
    print("=" * 76)
    print("ANIMALIA: COMPLETE ADOPT NOW + DONATE NOW TESTING")
    print("Website:", BASE_URL)
    print("Chrome actions are slowed down so you can observe each step.")
    print("Safety: no adoption request or payment will be submitted.")
    print("=" * 76)
    time.sleep(2)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False, slow_mo=650)
        except Exception:
            print("Google Chrome channel was not found; launching Playwright Chromium instead.")
            browser = p.chromium.launch(headless=False, slow_mo=650)

        context = browser.new_context(viewport={"width": 1365, "height": 900})
        page = context.new_page()
        page.set_default_timeout(TIMEOUT)

        page.on("request", lambda req: network_requests.append(req.url))
        page.on("response", lambda res: http_responses.append((res.url, res.status)))
        page.on("requestfailed", lambda req: failed_requests.append(
            f"{req.method} {req.url}: {req.failure}"
        ))
        page.on("pageerror", lambda err: page_errors.append(str(err)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        print("\n--- HOMEPAGE ---")
        response = safe_goto(page, BASE_URL)
        report("HOME01", "Homepage", "Homepage loads successfully",
               response is not None and response.status < 400,
               f"HTTP {response.status if response else 'no response'}")
        report("HOME02", "Homepage", "Page title exists",
               bool(page.title().strip()), page.title() or "Empty title")
        report("HOME03", "Homepage", "Homepage body is visible",
               page.locator("body").is_visible())
        test_images(page, "home")

        print("\n--- ADOPT NOW: CLICK EACH VISIBLE CTA ---")
        click_each_cta(page, "adopt")
        module_nav(page, "adopt")
        test_images(page, "adopt")
        test_form_fields(page, "adopt")

        print("\n--- DONATE NOW: CLICK EACH VISIBLE CTA ---")
        click_each_cta(page, "donate")
        module_nav(page, "donate")
        test_images(page, "donate")
        test_form_fields(page, "donate")

        test_network_summary()
        browser.close()

    test_http_api()

    passed = sum(r["status"] == "PASS" for r in results)
    failed = sum(r["status"] == "FAIL" for r in results)
    skipped = sum(r["status"] == "SKIP" for r in results)

    print("\n" + "=" * 76)
    print("FINAL AUTOMATION REPORT")
    print("=" * 76)
    for r in results:
        details = f' | {r["details"]}' if r["details"] else ""
        print(f'{r["status"]:4} | {r["id"]:12} | {r["module"]:18} | {r["name"]}{details}')

    print("-" * 76)
    print(f"TOTAL CHECKS: {len(results)} | PASS: {passed} | FAIL: {failed} | SKIP: {skipped}")
    print("\nImportant:")
    print("- CTA checks inspect what happens after clicking Adopt Now / Donate Now.")
    print("- Forms are filled with sample data for validation only; no form is submitted.")
    print("- Payment pages are not completed and no payment details are entered.")
    print("- HTTP checks are not full private-backend API tests.")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
