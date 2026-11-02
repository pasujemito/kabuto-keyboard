#include "../src/access_logic.h"
#include <cassert>
#include <iostream>
int main(){
    assert(isValidPin("123456")&&isValidPin("correct horse")&&isValidPin(std::string(32,'x')));
    assert(!isValidPin("12345")&&!isValidPin(std::string(33,'x'))&&!isValidPin("12345\n")&&!isValidPin("caf\xc3\xa9!!"));
    assert(loginLockoutMs(0)==0&&loginLockoutMs(4)==0&&loginLockoutMs(5)==30000&&loginLockoutMs(6)==60000);
    assert(loginLockoutMs(10)==900000&&loginLockoutMs(4000000000U)==900000);
    assert(cookieValue("kabuto_session=abc","kabuto_session")=="abc");
    assert(cookieValue("theme=dark; kabuto_session=abc; x=1","kabuto_session")=="abc");
    assert(cookieValue("not_kabuto_session=abc","kabuto_session")=="");
    assert(cookieValue("","kabuto_session")==""&&cookieValue("kabuto_session=","kabuto_session")=="");
    assert(constantTimeEquals("abc","abc")&&!constantTimeEquals("abc","abd")&&!constantTimeEquals("abc","ab"));
    // Sessions: a login takes an empty slot, then the one unused longest, so a
    // phone in use stays logged in however often something else logs in.
    SessionSlots<3> s;
    s.add("phone");s.add("laptop");s.add("script1");
    assert(s.touch("phone")&&!s.touch("nope")&&!s.touch(""));
    s.add("script2");                                    // the laptop was unused longest: it goes
    assert(s.touch("phone")&&!s.touch("laptop")&&s.touch("script1")&&s.touch("script2"));
    s.touch("phone");for(int i=0;i<10;++i){s.add("x"+std::to_string(i));s.touch("phone");}
    assert(s.touch("phone"));                            // used between logins: never dropped
    // Kept across restarts: saved and loaded as text, the order of use with them.
    SessionSlots<3> r;r.load(s.save());
    assert(r.touch("phone")&&r.clock>=s.clock&&!r.touch("laptop"));
    r.add("new");assert(r.touch("phone"));               // the restored order still decides
    r.load("abc:5,broken,:7,def:9");assert(r.touch("abc")&&r.touch("def")&&r.clock>=9);   // damaged entries skipped
    r.load("");assert(!r.touch("abc"));
    s.clear();assert(!s.touch("phone")&&s.save().empty());
    std::cout<<"access logic tests passed\n";
}
