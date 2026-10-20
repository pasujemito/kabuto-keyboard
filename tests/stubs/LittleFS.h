#pragma once
#include <Arduino.h>
#include <map>
#include <memory>
#include <cstring>
class File {
    std::shared_ptr<std::string> content_;
    std::size_t at_=0;
public:
    File()=default;
    explicit File(std::shared_ptr<std::string> data):content_(data){}
    explicit operator bool()const{return bool(content_);}
    int read(){return content_&&at_<content_->size()?static_cast<unsigned char>((*content_)[at_++]):-1;}
    std::size_t readBytes(char* dest,std::size_t n){std::size_t i=0;for(;i<n;++i){int c=read();if(c<0)break;dest[i]=c;}return i;}
    std::size_t write(uint8_t c){content_->push_back(c);return 1;}
    std::size_t write(const uint8_t* data,std::size_t n){content_->append(reinterpret_cast<const char*>(data),n);return n;}
    String readString(){return *content_;}
    void close(){}
};
struct TestLittleFS {
    std::map<std::string,std::shared_ptr<std::string>> files;
    bool begin(bool){return true;}
    bool exists(const char* name){return files.count(name);}
    File open(const char* name,const char* mode){
        if(*mode=='w')files[name]=std::make_shared<std::string>();
        auto found=files.find(name);return found==files.end()?File():File(found->second);
    }
};
extern TestLittleFS LittleFS;
