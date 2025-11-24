#Class MyPDFUtils
from pdfminer.high_level import extract_text, extract_pages, LTPage
import os
from datetime import datetime
import re
import logging

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
        self.pdf_file_name = pdf_file_name
        self.pdf_file_name_without_folder = self.pdf_file_name.split(os.sep)[-1]
        self.pdf_file_version = self.get_file_version()
        self.extract_pages()
        self.parse_data_elements()
    
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
                    return
            if 'y0' in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["coordinateMaxLimits"]:
                elementY0Floor = int(element.y0)
                if elementY0Floor > self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["coordinateMaxLimits"]["y0"]:
                    return
                
        elementText = element.get_text()
        #If the last two characters of elementText are \n then remove them
        if elementText[-1:] == "\n":
            elementText = elementText[:-1]
        
        elementText = elementText.strip()
        
        #print("TextBox=" + elementText)
        if self.currentContext == None and elementText in self.vzwPdfVersions[self.pdf_file_version]["contextMap"]:
            self.currentContext = elementText
            #print("Context: " + self.currentContext)
        elif self.currentContext != None and elementText == self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["final"]:
            del self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]
            self.currentContext = None
            #print("Context: None")
        elif self.currentContext != None and \
            "callback" in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext] \
            and elementText not in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["skip"]:
            self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["callback"](elementText, element)

        #print("Element Type: " + eltype)
    
    def v2_append_amount(self, elementText):
        amountDict = {
            "amount": None
        }
        pattern = r'^(\w+\s\w+)\n.*\((\d{3}-\d{3}-\d{4})\)$'
        match = re.match(pattern, elementText)
        if match:
            amountDict['name'] = match.group(1)
            amountDict['phoneNum'] = match.group(2)
        else:
            elementText = elementText.replace("\n", " ")
            amountDict['description'] = elementText
        self.parsedData["amounts"].append(amountDict)
    
    def v2_parseChargesByLineSummary(self, elementText, element):
        if elementText.startswith("$"):
            self.parsedData["amounts"][self.amountIndex]["amount"] = elementText
            self.amountIndex += 1
        else:
            self.v2_append_amount(elementText)
        
    def v1_parseCharges(self, elementText, element):
        if not self.checkCoordinateLimits(element):
            return
    
        #print("v1_parseCharges: " + elementText)
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

    def checkCoordinateLimits(self, element):
        if "coordinateMaxLimits" in self.vzwPdfVersions[self.pdf_file_version]:
            if element.x1 > self.vzwPdfVersions[self.pdf_file_version]["coordinateMaxLimits"]["x1"]:
                return False
        return True
    
    def get_parsed_data(self):
        return self.parsedData