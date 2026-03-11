#pragma once

#ifdef _WIN32
    #ifdef WEBRTCWRAPPER_EXPORTS
        #define WRAPPER_API __declspec(dllexport)
    #else
        #define WRAPPER_API __declspec(dllimport)
    #endif
#else
    #define WRAPPER_API
#endif

extern "C" {
    // Callbacks
    typedef void (*OnLogCallback)(const char* msg);
    // Updated: Supports Binary (Audio) and Text
    typedef void (*OnMessageCallback)(const void* data, int size, bool isBinary);
    typedef void (*OnLocalSdpCallback)(const char* sdp);

    // Opaque Handle
    typedef void* WebRTCClientHandle;

    // Functions
    WRAPPER_API WebRTCClientHandle CreateWebRTCClient();
    WRAPPER_API void DestroyWebRTCClient(WebRTCClientHandle handle);
    WRAPPER_API void StartClient(WebRTCClientHandle handle, const char* iceServersJson, OnLogCallback logCb, OnMessageCallback msgCb, OnLocalSdpCallback sdpCb);
    WRAPPER_API void SetRemoteDescription(WebRTCClientHandle handle, const char* sdp, const char* type);
    WRAPPER_API void SendDataMessage(WebRTCClientHandle handle, const char* msg);
    
    // Send Binary Data (Audio)
    WRAPPER_API void SendBinaryMessage(WebRTCClientHandle handle, const unsigned char* data, int size);
}
