#Class MyPDFUtils
from pdfminer.high_level import extract_text, extract_pages, LTPage

class MyPDFUtils:

    def __init__(self, pdf_file_name):
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
                "dateInit": "01/01/2024",
                "dateEnd": "09/01/2024",
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
                            "Surcharges, taxes and gov fees"
                        ],
                        "callback": self.v2_parseChargesByLineSummary
                    }
                }
            }
        }

        self.parsedData = {
            "amounts": [],
            "account": None,
            "invoice": None,
        }
        self.currentContext = None
        self.amountIndex = 0
        self.pdf_file_name = pdf_file_name
        self.pdf_file_version = self.get_file_version()
        self.extract_pages()
        self.parse_data_elements()
        
        
    def get_file_version(self):
        '''
        File name should be in the format MyBill_MM.DD.YYYY.pdf
        extract the date from the file name and return the version of the file
        by looking up the date in the vzwPdfVersions dictionary
        '''
        #Extract date from file name
        date = self.pdf_file_name.split("_")[1].split(".")[0]
        #Check if date is within the range of any version
        for version in self.vzwPdfVersions:
            if date >= self.vzwPdfVersions[version]["dateInit"] and date <= self.vzwPdfVersions[version]["dateEnd"]:
                print("PDF File Version: " + version)
                return version
        return None
    
    def extract_pages(self):
        self.pdf_extracted_pages: list[LTPage] = []
        for pagenumber in self.vzwPdfVersions[self.pdf_file_version]["pagesToParse"]:
            for page_layout in extract_pages(self.pdf_file_name, page_numbers=[pagenumber]):
                self.pdf_extracted_pages.append(page_layout)
                print("Page Number: " + str(pagenumber))

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
        elementText = element.get_text()
        #If the last two characters of elementText are \n then remove them
        if elementText[-1:] == "\n":
            elementText = elementText[:-1]
        
        if eltype == "TextBox":
            print("TextBox=" + elementText)
            if self.currentContext == None and elementText in self.vzwPdfVersions[self.pdf_file_version]["contextMap"]:
                self.currentContext = elementText
                print("Context: " + self.currentContext)
            elif self.currentContext != None and elementText == self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["final"]:
                del self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]
                self.currentContext = None
                print("Context: None")
            elif self.currentContext != None and \
                "callback" in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext] \
                and elementText not in self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["skip"]:
                self.vzwPdfVersions[self.pdf_file_version]["contextMap"][self.currentContext]["callback"](elementText, element)

        print("Element Type: " + eltype)
        
    def v2_parseChargesByLineSummary(self, elementText, element):
        if elementText.startswith("Billing period"):
            self.parsedData["billingPeriod"] = elementText.split(":")[1].strip()
        elif elementText.startswith("Account:"):
            '''
            Account: 324XXXXXX-00001  \nInvoice: 8695XXXXXX\nBilling period: Jun 19 - Jul 18, 2024
            '''
            self.parsedData["account"] = elementText.split("\n")[0].split(":")[1].strip()
            self.parsedData["invoice"] = elementText.split("\n")[1].split(":")[1].strip()
        elif elementText.startswith("The total amount due for this month"):
            pass
        elif elementText.startswith("$"):
            self.parsedData["amounts"][self.amountIndex]["amount"] = elementText
            self.amountIndex += 1
        else:
            self.parsedData["amounts"].append(
                {
                    "description": elementText,
                    "amount": None
                }
            )
        
    def v1_parseCharges(self, elementText, element):
        if not self.checkCoordinateLimits(element):
            return
    
        print("v1_parseCharges: " + elementText)
        if elementText.startswith("$"):
            self.parsedData["amounts"][self.amountIndex]["amount"] = elementText
            self.amountIndex += 1
        else:
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