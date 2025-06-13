let socket;
let displayDiv = document.getElementById('textDisplay');
let server_available = false;
let mic_available = false;
let fullSentences = [];

const serverCheckInterval = 5000;

function generateUUID() {
    if (crypto.randomUUID) {
        return crypto.randomUUID(); // 최신 브라우저
    }
    // 구형 브라우저 호환
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        let r = Math.random() * 16 | 0,
            v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function getFormattedTimestamp() {
    const now = new Date();
    const YYYY = now.getFullYear();
    const MM = String(now.getMonth() + 1).padStart(2, '0'); // 월은 0부터 시작
    const DD = String(now.getDate()).padStart(2, '0');
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    return `${YYYY}${MM}${DD}${hh}${mm}`;
}

const sessionId = generateUUID();
const userId = "user_abc123";

function setupWebSocket() {
    socket = new WebSocket(STT_SERVER_URL);

    socket.onopen = function () {
        server_available = true;
        start_msg();
        console.log("🟢 WebSocket connected");
    };

    socket.onmessage = function (event) {
        let data = JSON.parse(event.data);
        console.log("📨 WebSocket message received:", data);

        if (data.type === 'realtime') {
            displayRealtimeText(data.text, displayDiv);
        }

        else if (data.type === 'fullSentence') {
            let sentenceSpan = document.createElement('span');
            sentenceSpan.textContent = data.text + " ";
        
            let labelSpan = document.createElement('span');
            labelSpan.textContent = `🏷️ ${data.label} ⏱️ ${data.stt_latency.toFixed(2)}s`;
        
            sentenceSpan.className = fullSentences.length % 2 === 0 ? 'yellow' : 'cyan';
            sentenceSpan.appendChild(labelSpan);
        
            let wrapper = document.createElement('div');
            wrapper.appendChild(sentenceSpan);
        
            fullSentences.push(wrapper.outerHTML);
            displayRealtimeText("", displayDiv);
        }
    };

    socket.onclose = function (event) {
        server_available = false;
        console.warn("🔴 WebSocket closed:", event);
    };

    socket.onerror = function (err) {
        console.error("❌ WebSocket error:", err);
    };
}

function displayRealtimeText(realtimeText, displayDiv) {
    let displayedText = fullSentences.join('') + realtimeText;
    displayDiv.innerHTML = displayedText;
}

function start_msg() {
    if (!mic_available)
        displayRealtimeText("🎤  please allow microphone access  🎤", displayDiv);
    else if (!server_available)
        displayRealtimeText("🖥️  please start server  🖥️", displayDiv);
    else
        displayRealtimeText("👄  start speaking  👄", displayDiv);
}

setInterval(() => {
    if (!server_available || socket.readyState === WebSocket.CLOSED) {
        setupWebSocket();
    }
}, serverCheckInterval);

setupWebSocket();  // ✅ 최초 연결 시도
start_msg();       // 초기 메시지 출력

navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
        let audioContext = new AudioContext();
        let source = audioContext.createMediaStreamSource(stream);
        let processor = audioContext.createScriptProcessor(256, 1, 1);

        source.connect(processor);
        processor.connect(audioContext.destination);
        mic_available = true;
        start_msg();

        processor.onaudioprocess = function (e) {
            let inputData = e.inputBuffer.getChannelData(0);
            let outputData = new Int16Array(inputData.length);

            for (let i = 0; i < inputData.length; i++) {
                outputData[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
            }

            if (socket && socket.readyState === WebSocket.OPEN) {
                let metadata = JSON.stringify({ 
                    sampleRate: audioContext.sampleRate,
                    timestamp: getFormattedTimestamp(),
                    sessionId: sessionId,
                    userId: userId
                 });
                let metadataBytes = new TextEncoder().encode(metadata);
                let metadataLength = new ArrayBuffer(4);
                let metadataLengthView = new DataView(metadataLength);
                metadataLengthView.setInt32(0, metadataBytes.byteLength, true);
                let combinedData = new Blob([metadataLength, metadataBytes, outputData.buffer]);
                socket.send(combinedData);
            }
        };
    })
    .catch(e => {
        console.error("🎤 Microphone error:", e);
        displayRealtimeText("❌ Microphone access denied", displayDiv);
    });
