import pymsn.service.SOAPService as SOAPService
import pymsn.service.SingleSignOn as SSO
import pymsn.service.AddressBook as AddressBook
import gobject
import logging

logging.basicConfig(level=logging.DEBUG)

NS_TEMP = "urn:xmethods-Temperature"
class TemperatureService(SOAPService.SOAPService):
    def __init__(self, url):
        SOAPService.SOAPService.__init__(self, url)

    def _soap_action(self, method):
        return ""

    def _method_namespace(self, method):
        return NS_TEMP

#test = TemperatureService("http://services.xmethods.net/soap/servlet/rpcrouter")
#test.getTemp(("string", "zipcode", "10000"))

#print '------------------------------------------------'
def membership_cb(*args):
    pass

def sso_cb(soap_response, *tokens):
    abook = None
    for token in tokens:
        if token.service_address == SSO.LiveService.CONTACTS[0]:
            abook = AddressBook.AddressBook(token)
            sharing = AddressBook.Sharing(token)
            break
    abook.ABFindAll(membership_cb)
    sharing.FindMembership(membership_cb)


sso = SSO.SingleSignOn("kimbix@hotmail.com", "linox45")
sso.RequestMultipleSecurityTokens(sso_cb, (), SSO.LiveService.CONTACTS)


gobject.MainLoop().run()
