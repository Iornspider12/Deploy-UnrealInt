cmake_minimum_required(VERSION 3.15)
project(WebRTCWrapper)

# Use vcpkg toolchain (assuming user builds with cmake --preset or passes toolchain)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(LibDataChannel CONFIG REQUIRED)
find_package(OpenSSL REQUIRED)

add_library(WebRTCWrapper SHARED WebRTCWrapper.cpp WebRTCWrapper.h)

target_link_libraries(WebRTCWrapper PRIVATE LibDataChannel::LibDataChannel OpenSSL::SSL OpenSSL::Crypto)

target_compile_definitions(WebRTCWrapper PRIVATE WEBRTCWRAPPER_EXPORTS)
