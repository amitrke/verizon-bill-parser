#Class MyPDFUtils
from pdfminer.high_level import extract_pages, LTPage
import os
from datetime import datetime
import re
import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

class MyPDFUtils:

    def __init__(self, pdf_file_name, log_level=logging.ERROR):
        logger.setLevel(log_level)

        self.vzwPdfVersions = {
            "v1": {
                "dateInit": "01/01/2022",
                "dateEnd": "12/01/2022",
                "pagesToParse": [0],
                "coordinateMaxLimits": {
                    "x1": 385
                },
                "contextMap": {
                    ".": {
                        "final": "abcd",
                        "skip": [
                            "am a test",
                            "Smartphone"
                        ],
                        "callback": self.v1_parseCharges
                    }
                }
            },
            "v2": {
                "dateInit": "10/01/2023",
                "dateEnd": "01/01/2026",
                "detectVersionFromContent": {
                    "page": 0,
                    "text": "Bill date\nAccount number\nInvoice number\n",
                    "x0": 276,
                    "y0": 215,
                },
                "pagesToParse": [2],
                "contextMap": {
                    "Bill summary by line": {
                        "final": "abcd",
                        "skip": [
                            "am a test",
                            "Smartphone",
                            "Questions about your bill?\nverizon.com/support\n800-922-0204",
                            "Review your bill online",
                            "An itemized bill breakdown of all\ncharges and credits is available on\nthe My Verizon app and online.",
                            "Scan the QR code\nwith your camera\napp or go to\ngo.vzw.com/bill.",
                            "Surcharges, taxes and gov fees",
                            "New plan added",
                            "New device added",
                            "Plan changed",
                            "Perk added",
                            "Perk removed",
                            "Device upgraded",
                            "Service added",
                            "Service removed",
                        ],
                        "callback": self.v2_parseChargesByLineSummary,
                        "coordinateMaxLimits": {
                            "x0": 330
                        }
                    }
                }
            }
        }

        self.parsedData = {
            "amounts": [],
            # "account": None,
            # "invoice": None,
            "fileName": pdf_file_name
        }
        self.currentContext = None
        self.amountIndex = 0
        # Keep a short history of recent text boxes to detect headers that may
        # be split across multiple PDF text elements in newer bill formats.
        self._recent_text_boxes: deque[str] = deque(maxlen=8)
        # Used by v2 parsing to ignore the grand-total amount immediately after a "Total:" label.
        self._v2_total_y0: Optional[float] = None
        # Used by v2 parsing to ignore the Account-wide charges & credits amount (not a per-line charge).
        self._v2_accountwide_y0: Optional[float] = None
        self._v2_accountwide_token_buf: list[str] = []
        # Used by v2 parsing to pair $-amounts with line rows reliably.
        self._v2_pending_amount_rows: deque[int] = deque()
        self.pdf_file_name = pdf_file_name
        self.pdf_file_name_without_folder = self.pdf_file_name.split(os.sep)[-1]
        self.pdf_file_version = self.get_file_version()

        if not self.pdf_file_version:
            raise ValueError(
                f"Unable to determine Verizon bill PDF version for file: {self.pdf_file_name}"
            )

        self.extract_pages()
        self.parse_data_elements()

    @staticmethod
    def _normalize_text(text: str) -> str:
        # Collapse whitespace and lowercase for robust matching.
        return " ".join(text.split()).strip().lower()
    
    def get_file_version_from_filename(self):
        #Extract date from file name
        dateParts = self.pdf_file_name_without_folder.split("_")[1].split(".")
        #Date object
        date = datetime(int(dateParts[2]), int(dateParts[0]), int(dateParts[1]))
        self.parsedData["billDate"] = date.strftime("%m/%d/%Y")
        #Check if date is within the range of any version
        for version in self.vzwPdfVersions:
            dateInit = datetime.strptime(self.vzwPdfVersions[version]["dateInit"], "%m/%d/%Y")
            dateEnd = datetime.strptime(self.vzwPdfVersions[version]["dateEnd"], "%m/%d/%Y")
            if date >= dateInit and date <= dateEnd:
                logger.debug(f"File {self.pdf_file_name} is version {version}")
                return version
        logger.warning(f"File {self.pdf_file_name} is not within any version range")
        return None
    
    def match_coordinates(self, element, detectObj):
        '''
        Check if the element coordinates match the detectObj coordinates
        plus or minus 5 pixel
        '''
        elementX0Floor = int(element.x0)
        elementY0Floor = int(element.y0)
        if elementX0Floor >= detectObj["x0"] - 5 and elementX0Floor <= detectObj["x0"] + 5 \
            and elementY0Floor >= detectObj["y0"] - 5 and elementY0Floor <= detectObj["y0"] + 5:
            return True
        return False

    def get_file_version_from_content(self) -> str:
        for version in self.vzwPdfVersions:
            if "detectVersionFromContent" in self.vzwPdfVersions[version]:
                detectObj = self.vzwPdfVersions[version]["detectVersionFromContent"]
                pageNumber = detectObj["page"]
                for page_layout in extract_pages(self.pdf_file_name, page_numbers=[pageNumber]):
                    for element in page_layout:
                        if element.__class__.__name__ == "LTTextBoxHorizontal":
                            if self.match_coordinates(element, detectObj) \
                                and element.get_text() == detectObj["text"]:
                                return version
                            # elif 'Bill date' in element.get_text():
                            #     print("Bill date found")       
        return None
        
    def get_file_version(self):
        '''
        File name should be in the format MyBill_MM.DD.YYYY.pdf
        extract the date from the file name and return the version of the file
        by looking up the date in the vzwPdfVersions dictionary
        '''
        logger.debug(f"Get file version for file: {self.pdf_file_name}")
        #Check if the file is a PDF file
        if not self.pdf_file_name.endswith(".pdf"):
            raise Exception(f"File {self.pdf_file_name} is not a PDF file")
        
        #Check if the file name is in the MyBill_MM.DD.YYYY.pdf format
        if not self.pdf_file_name_without_folder.startswith("MyBill_"):
            logger.debug(f"File {self.pdf_file_name} does not start with MyBill_")
            return self.get_file_version_from_content()
        else:
            logger.debug(f"File {self.pdf_file_name} starts with MyBill_")
            return self.get_file_version_from_filename()

    def extract_pages(self):
        self.pdf_extracted_pages: list[LTPage] = []
        for pagenumber in self.vzwPdfVersions[self.pdf_file_version]["pagesToParse"]:
            for page_layout in extract_pages(self.pdf_file_name, page_numbers=[pagenumber]):
                self.pdf_extracted_pages.append(page_layout)
                #print("Page Number: " + str(pagenumber))

    def parse_data_elements(self):
        for page in self.pdf_extracted_pages:
            for element in page:
                # If element text is present then log it (avoid noisy empty text).
                if hasattr(element, "get_text"):
                    text = element.get_text()
                    if text and text.strip():
                        logger.debug(f"Element Text: {text}")

                if element.__class__.__name__ == "LTTextContainer":
                    self.parse_element("TextLine", element)
                elif element.__class__.__name__ == "LTTextBoxHorizontal":
                    self.parse_element("TextBox", element)
                elif element.__class__.__name__ == "LTChar":
                    self.parse_element("Char", element)
                elif element.__class__.__name__ == "LTAnno":
                    self.parse_element("Anno", element)
    
    def parse_element(self, eltype: str, element):
        if eltype != "TextBox":
            return
        
        if self.currentContext != None and 'coordinateMaxLimits' in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]:
            if 'x0' in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["coordinateMaxLimits"]:
                elementX0Floor = int(element.x0)
                if elementX0Floor > self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["coordinateMaxLimits"]["x0"]:
                    # logger.debug(f"Element x0 {elementX0Floor} exceeds max limit, text: {element.get_text()}")
                    return
            if 'y0' in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["coordinateMaxLimits"]:
                elementY0Floor = int(element.y0)
                if elementY0Floor > self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["coordinateMaxLimits"]["y0"]:
                    # logger.debug(f"Element y0 {elementY0Floor} exceeds max limit, text: {element.get_text()}")
                    return
                
        elementText = element.get_text()
        #If the last two characters of elementText are \n then remove them
        if elementText.endswith("\n"):
            elementText = elementText[:-1]
        
        elementText = elementText.strip()

        # Track recent text boxes for multi-box header detection.
        if elementText:
            self._recent_text_boxes.append(elementText)
        
        logger.debug(f"TextBox={elementText}")

        if self.currentContext is None:
            context_map = self.vzwPdfVersions[self.pdf_file_version]["contextMap"]

            # 1) Exact match (historical behavior)
            if elementText in context_map:
                self.currentContext = elementText
                logger.debug(f"Context: {self.currentContext}")
            else:
                # 2) Robust match: join last N text boxes and compare against context keys.
                normalized_keys = {self._normalize_text(k): k for k in context_map.keys()}
                recent_normalized = [self._normalize_text(t) for t in self._recent_text_boxes if t]
                max_window = min(len(recent_normalized), 8)
                matched_key = None
                for window_size in range(2, max_window + 1):
                    candidate = " ".join(recent_normalized[-window_size:])
                    if candidate in normalized_keys:
                        matched_key = normalized_keys[candidate]
                        break

                if matched_key is not None:
                    self.currentContext = matched_key
                    logger.debug(f"Context: {self.currentContext} (via joined text boxes)")
        elif self.currentContext != None and elementText == self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["final"]:
            del self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]
            self.currentContext = None
            logger.debug("Context: None")
        elif self.currentContext != None and \
            "callback" in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext] \
            and elementText not in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["skip"]:
            self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["callback"](elementText, element)
            logger.debug(f"Callback invoked for context {self.currentContext} with text: {elementText}")

        logger.debug(f"Element Type: {eltype}")
    
    def v2_append_amount(self, elementText):
        amountDict = {
            "amount": None
        }

        # Common shapes observed:
        # - "First Last\nDevice Model"  (phone sometimes appears as its own text box)
        # - other descriptive lines
        lines = [ln.strip() for ln in elementText.split("\n") if ln.strip()]
        if len(lines) >= 2:
            # Treat first line as a name when it looks like "First Last".
            if re.match(r"^[A-Za-z]+\s+[A-Za-z]+$", lines[0]):
                amountDict["name"] = lines[0]
                amountDict["description"] = " ".join(lines[1:])
            else:
                amountDict["description"] = " ".join(lines)
        else:
            amountDict["description"] = elementText.replace("\n", " ")

        self.parsedData["amounts"].append(amountDict)
        self._v2_pending_amount_rows.append(len(self.parsedData["amounts"]) - 1)
        logger.debug(f"Appended amount: {amountDict}")
    
    def v2_parseChargesByLineSummary(self, elementText, element):
        normalized = self._normalize_text(elementText)

        # Detect and skip the Account-wide charges & credits row.
        # This row is not a per-line charge, but its $0.00 (or similar) appears in the same table and can
        # shift amount alignment if we don't explicitly ignore it.
        accountwide_full = "account-wide charges & credits"
        accountwide_tokens = {"account-wide", "charges", "&", "credits"}

        if normalized == accountwide_full:
            self._v2_accountwide_y0 = float(getattr(element, "y0", 0.0))
            logger.debug("Skipping v2 account-wide label")
            return

        if normalized in accountwide_tokens:
            self._v2_accountwide_token_buf.append(normalized)
            # When we have seen all tokens (order-insensitive), treat it as the account-wide label.
            if set(self._v2_accountwide_token_buf) >= accountwide_tokens:
                self._v2_accountwide_y0 = float(getattr(element, "y0", 0.0))
                self._v2_accountwide_token_buf.clear()
                logger.debug("Skipping v2 account-wide label (split tokens)")
            else:
                logger.debug(f"Skipping v2 account-wide token: {elementText}")
            return

        # Ignore totals row; the $-amount on the same line is the grand total, not a line item.
        if normalized == "total:":
            self._v2_total_y0 = float(getattr(element, "y0", 0.0))
            logger.debug("Skipping v2 total label")
            return

        if elementText.startswith("$"):
            amount_y0 = float(getattr(element, "y0", 0.0))

            # Skip account-wide amount if it appears on the same row.
            if self._v2_accountwide_y0 is not None and abs(amount_y0 - self._v2_accountwide_y0) <= 6:
                logger.debug(f"Skipping v2 account-wide amount: {elementText}")
                self._v2_accountwide_y0 = None
                return

            # Skip grand total amount if it appears on the same row as the Total: label.
            if self._v2_total_y0 is not None and abs(amount_y0 - self._v2_total_y0) <= 6:
                logger.debug(f"Skipping v2 grand total amount: {elementText}")
                self._v2_total_y0 = None
                return

            # Only assign amounts to rows we've explicitly created.
            if not self._v2_pending_amount_rows:
                logger.debug(f"Skipping v2 amount without pending row: {elementText}")
                return

            row_index = self._v2_pending_amount_rows.popleft()
            self.parsedData["amounts"][row_index]["amount"] = elementText
        else:
            # If the phone number comes as its own text box, attach it to the last row.
            phone_match = re.match(r"^\(?\s*(\d{3}-\d{3}-\d{4})\s*\)?$", elementText.strip())
            if phone_match and self.parsedData["amounts"]:
                last = self.parsedData["amounts"][-1]
                if last.get("phoneNum") is None:
                    last["phoneNum"] = phone_match.group(1)
                    logger.debug(f"Attached phoneNum to last row: {last['phoneNum']}")
                    return
            self.v2_append_amount(elementText)
        logger.debug(f"v2_parseChargesByLineSummary: {elementText}")
        
    def v1_parseCharges(self, elementText, element):
        if not self.checkCoordinateLimits(element):
            return
    
        if elementText.startswith("$"):
            self.parsedData["amounts"][self.amountIndex]["amount"] = elementText
            self.amountIndex += 1
        else:
            elementText = elementText.replace("\n", " ")
            self.parsedData["amounts"].append(
                    {
                        "description": elementText,
                        "amount": None
                    }
                )
        logger.debug(f"v1_parseCharges: {elementText}")

    def checkCoordinateLimits(self, element):
        if "coordinateMaxLimits" in self.vzwPdfVersions[self.pdf_file_version]:
            if element.x1 > self.vzwPdfVersions[self.pdf_file_version]["coordinateMaxLimits"]["x1"]:
                return False
        return True
    
    def get_parsed_data(self):
        return self.parsedData