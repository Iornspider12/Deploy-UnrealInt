#include "WebRTCWrapper.h"
#include "rtc/rtc.hpp"
#include <iostream>
#include <string>
#include <memory>
#include <variant>

class WebRTCClientInternal {
public:
    std::shared_ptr<rtc::PeerConnection> pc;
    std::shared_ptr<rtc::DataChannel> dc;
    
    OnLogCallback logCallback = nullptr;
    OnMessageCallback msgCallback = nullptr;
    OnLocalSdpCallback sdpCallback = nullptr;

    WebRTCClientInternal() {}

    void Log(const std::string& msg) {
        if (logCallback) logCallback(msg.c_str());
    }

    void Start(const std::string& iceServersJson, OnLogCallback logCb, OnMessageCallback msgCb, OnLocalSdpCallback sdpCb) {
        logCallback = logCb;
        msgCallback = msgCb;
        sdpCallback = sdpCb;

        try {
            rtc::Configuration config;
            config.iceServers.emplace_back("stun:stun.l.google.com:19302"); 

            pc = std::make_shared<rtc::PeerConnection>(config);
            
            // Setup DataChannel (Optimized for Unreliable/Low-Latency Audio)
            rtc::DataChannelInit config;
            config.ordered = false;
            config.maxRetransmits = 0;
            dc = pc->createDataChannel("chat", config);
            
            dc->onOpen([this]() {
                Log("DataChannel OPEN inside Wrapper! (Audio Enabled Version)");
            });

            dc->onMessage([this](auto data) {

                 if (std::holds_alternative<std::string>(data)) {
                     std::string msg = std::get<std::string>(data);
                     Log(std::string("🔵 DLL received TEXT: ") + msg.substr(0, std::min(50, (int)msg.size())));
                     if (msgCallback) msgCallback(msg.c_str(), (int)msg.size(), false);
                 } else {
                     auto bytes = std::get<rtc::binary>(data);
                     // Log first binary receipt
                     static int binaryCount = 0;
                     if (++binaryCount % 50 == 0 || binaryCount == 1) {
                         Log(std::string("🟢 DLL received BINARY #") + std::to_string(binaryCount) + 
                             std::string(" size: ") + std::to_string(bytes.size()));
                     }
                     // Audio Data (Binary)
                     if (msgCallback) msgCallback(bytes.data(), (int)bytes.size(), true);
                 }
            });

            pc->onGatheringStateChange([this](rtc::PeerConnection::GatheringState state) {
               if (state == rtc::PeerConnection::GatheringState::Complete) {
                   if (auto localDesc = pc->localDescription()) {
                       if (sdpCallback) sdpCallback(std::string(*localDesc).c_str());
                   }
               }
            });

            pc->setLocalDescription();

        } catch (const std::exception& e) {
            Log(std::string("Wrapper Exception: ") + e.what());
        }
    }

    void SetRemoteDescription(const std::string& sdp, const std::string& type) {
        if (pc) {
             try {
                pc->setRemoteDescription(rtc::Description(sdp, type));
             } catch(const std::exception& e) {
                 Log(std::string("SetRemoteDescription Error: ") + e.what());
             }
        }
    }

    void SendMessage(const std::string& msg) {
        if (dc && dc->isOpen()) {
            dc->send(msg);
        } else {
            Log("DataChannel not ready to send.");
        }
    }

    void SendBinary(const unsigned char* data, int size) {
        if (dc && dc->isOpen()) {
            // Convert to std::byte for libdatachannel
            const std::byte* byteData = reinterpret_cast<const std::byte*>(data);
            dc->send(byteData, size);
            
            // Diagnostic: confirm send succeeded (log every 50th packet to avoid spam)
            static int sendCount = 0;
            if (++sendCount % 50 == 0) {
                Log(std::string("✅ Binary sent: ") + std::to_string(size) + " bytes (total: " + std::to_string(sendCount) + ")");
            }
        } else {
             // Silent fail or Log? Silent to avoid spamming logs 60 times a second
        }
    }
};

// --- C API Implementation ---

extern "C" {
    WRAPPER_API WebRTCClientHandle CreateWebRTCClient() {
        return new WebRTCClientInternal();
    }

    WRAPPER_API void DestroyWebRTCClient(WebRTCClientHandle handle) {
        if (handle) {
            delete static_cast<WebRTCClientInternal*>(handle);
        }
    }

    WRAPPER_API void StartClient(WebRTCClientHandle handle, const char* iceServersJson, OnLogCallback logCb, OnMessageCallback msgCb, OnLocalSdpCallback sdpCb) {
        if (handle) {
            static_cast<WebRTCClientInternal*>(handle)->Start(iceServersJson, logCb, msgCb, sdpCb);
        }
    }

    WRAPPER_API void SetRemoteDescription(WebRTCClientHandle handle, const char* sdp, const char* type) {
        if (handle) {
            static_cast<WebRTCClientInternal*>(handle)->SetRemoteDescription(sdp, type);
        }
    }

    WRAPPER_API void SendDataMessage(WebRTCClientHandle handle, const char* msg) {
        if (handle) {
            static_cast<WebRTCClientInternal*>(handle)->SendMessage(msg);
        }
    }

    WRAPPER_API void SendBinaryMessage(WebRTCClientHandle handle, const unsigned char* data, int size) {
        if (handle) {
            static_cast<WebRTCClientInternal*>(handle)->SendBinary(data, size);
        }
    }
}
