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
    std::cout<<"access logic tests passed\n";
}
