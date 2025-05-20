import { useState, useRef, useEffect } from 'react';
import { Image, StyleSheet, TouchableOpacity, AppState, Text, TextInput, View, Platform } from 'react-native';
import { CameraView, useCameraPermissions, BarcodeScanningResult } from 'expo-camera';
import ParallaxScrollView from '@/components/ParallaxScrollView';
import { ThemedText } from '@/components/ThemedText';
import { ThemedView } from '@/components/ThemedView';
import * as Clipboard from 'expo-clipboard';
import BackgroundService from 'react-native-background-actions';

type Message = {
  type: 'pairing_response' | 'clipboard_update';
  text?: string;
  success?: boolean;
  source?: string;
  timestamp?: number;
};

export default function HomeScreen() {
  const [facing, setFacing] = useState<'front' | 'back'>('back');
  const [permission, requestPermission] = useCameraPermissions();
  const [scanned, setScanned] = useState(false);
  const [showCamera, setShowCamera] = useState(false);
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [receivedContent, setReceivedContent] = useState<string>('');
  const [lastSentContent, setLastSentContent] = useState<string>('');
  const [isConnected, setIsConnected] = useState(false);
  const [serverUrl, setServerUrl] = useState<string>('');

  const socketRef = useRef<WebSocket | null>(null);
  //const appState = useRef(AppState.currentState);


  // Background task for clipboard monitoring
  const backgroundClipboardTask = async (taskData: any) => {
    let lastContent = '';
    while (BackgroundService.isRunning()) {
      try {
        const currentContent = await Clipboard.getStringAsync();
        if (currentContent && currentContent !== lastContent) {
          if (socketRef.current?.readyState === WebSocket.OPEN) {
            const message: Message = {
              type: 'clipboard_update',
              text: currentContent,
              timestamp: Date.now()
            };
            socketRef.current.send(JSON.stringify(message));
            lastContent = currentContent;
          }
        }
      } catch (error) {
        console.error('Background task error:', error);
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  };

  // Handle app state changes
  useEffect(() => {
    const handleAppStateChange = async (nextAppState: string) => {
      if (nextAppState === 'background' && isConnected) {
        await BackgroundService.start(backgroundClipboardTask, {
          taskName: 'Clipboard Sync',
          taskTitle: 'Syncing clipboard',
          taskDesc: 'Watching for clipboard changes',
          taskIcon: { name: 'ic_notification', type: 'mipmap' },
          linkingURI: 'yourapp://clipboard-sync',
        });
      } else if (nextAppState === 'active') {
        await BackgroundService.stop();
      }
    };

    const sub = AppState.addEventListener('change', handleAppStateChange);//change between foreground and background
    return () => {
      sub.remove();
      BackgroundService.stop();
    };
  }, [isConnected]);

  // Clipboard monitoring in foreground
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const content = await Clipboard.getStringAsync();
        if (content && content !== lastSentContent && socketRef.current?.readyState === WebSocket.OPEN) {
          const message: Message = {
            type: 'clipboard_update',
            text: content,
            timestamp: Date.now()
          };
          socketRef.current.send(JSON.stringify(message));
          setLastSentContent(content);
        }
      } catch (error) {
        console.error('Clipboard monitoring error:', error);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [lastSentContent]);

  // Handle WebSocket messages(incoming clipboard data from laptop's server)
  const handleWebSocketMessage = (event: WebSocketMessageEvent) => {
    try {
      const message: Message = JSON.parse(event.data);
      
      if (message.type === 'clipboard_update' && message.text) {
        setReceivedContent(message.text);
        Clipboard.setStringAsync(message.text);
      } else if (message.type === 'pairing_response') {
        setIsConnected(message.success || false);
      }
    } catch (error) {
      console.error('Message parsing error:', error);
    }
  };

  // QR Code scanning handler
  const handleBarCodeScanned = ({ data }: BarcodeScanningResult) => {
    setScanned(true);
    setShowCamera(false);
    
    try {
      const url = new URL(data);
      const deviceId = url.pathname.split('/').pop();
      const pairingCode = url.searchParams.get('code');
      
      if (deviceId && pairingCode) {
        setPairingCode(pairingCode);
        setServerUrl(`ws://${url.host}/ws/${deviceId}`);
        connectWebSocket(`ws://${url.host}/ws/${deviceId}`, pairingCode);
      }
    } catch {
      alert('Invalid QR code. Please scan the correct code from your computer.');
    }
  };

  // WebSocket connection
  const connectWebSocket = (url: string, code: string) => {
    if (socketRef.current) {
      socketRef.current.close();
    }

    const ws = new WebSocket(url);
    
    ws.onopen = () => {
      setIsConnected(true);
      ws.send(JSON.stringify({
        type: 'pairing_request',
        code: code,
        device: Platform.OS
      }));
    };
    
    ws.onmessage = handleWebSocketMessage;
    
    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setIsConnected(false);
    };
    
    ws.onclose = () => {
      setIsConnected(false);
    };
    
    socketRef.current = ws;
  };

  // Manual connection
  const handleManualConnect = () => {
    if (serverUrl && pairingCode) {
      connectWebSocket(serverUrl, pairingCode);
    }
  };

  if (!permission?.granted) {
    return (
      <ThemedView style={styles.container}>
        <ThemedText>Camera permission required</ThemedText>
        <TouchableOpacity style={styles.button} onPress={requestPermission}>
          <ThemedText style={styles.buttonText}>Grant Permission</ThemedText>
        </TouchableOpacity>
      </ThemedView>
    );
  }

  if (showCamera) {
    return (
      <ThemedView style={styles.container}>
        <CameraView
          style={styles.camera}
          facing={facing}
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
          onBarcodeScanned={scanned ? undefined : handleBarCodeScanned}
        />
        <TouchableOpacity style={styles.button} onPress={() => setShowCamera(false)}>
          <ThemedText style={styles.buttonText}>Cancel</ThemedText>
        </TouchableOpacity>
      </ThemedView>
    );
  }

  return (
    <ParallaxScrollView
      headerBackgroundColor={{ light: '#A1CEDC', dark: '#1D3D47' }}
      headerImage={
        <Image
          source={require('@/assets/images/partial-react-logo.png')}
          style={styles.reactLogo}
        />
      }
    >
      <ThemedView style={styles.titleContainer}>
        <ThemedText type="title">Clipboard Sync</ThemedText>
        <ThemedText>{isConnected ? 'Connected ✅' : 'Disconnected ❌'}</ThemedText>
      </ThemedView>

      <ThemedView style={styles.stepContainer}>
        <ThemedText type="subtitle">Pair Your Device</ThemedText>
        <TouchableOpacity
          style={styles.scanButton}
          onPress={() => {
            setScanned(false);
            setShowCamera(true);
          }}
        >
          <ThemedText style={styles.buttonText}>Scan QR Code</ThemedText>
        </TouchableOpacity>

        {pairingCode && (
          <ThemedView style={styles.codeContainer}>
            <ThemedText>Pairing Code: {pairingCode}</ThemedText>
            <TextInput
              style={styles.input}
              placeholder="Enter server URL (ws://...)"
              value={serverUrl}
              onChangeText={setServerUrl}
            />
            <TouchableOpacity 
              style={styles.connectButton} 
              onPress={handleManualConnect}
            >
              <ThemedText style={styles.buttonText}>Connect Manually</ThemedText>
            </TouchableOpacity>
          </ThemedView>
        )}
      </ThemedView>

      <ThemedView style={styles.stepContainer}>
        <ThemedText type="subtitle">Clipboard Content</ThemedText>
        <View style={styles.clipboardBox}>
          <Text selectable={true}>
            {receivedContent || 'Nothing received yet'}
          </Text>
        </View>
      </ThemedView>
    </ParallaxScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  camera: {
    width: '100%',
    height: '70%',
  },
  titleContainer: {
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
    marginBottom: 20,
  },
  stepContainer: {
    gap: 8,
    marginBottom: 20,
  },
  reactLogo: {
    height: 178,
    width: 290,
    bottom: 0,
    left: 0,
    position: 'absolute',
  },
  scanButton: {
    backgroundColor: '#007AFF',
    padding: 15,
    borderRadius: 5,
    marginTop: 10,
    alignItems: 'center',
  },
  button: {
    backgroundColor: '#FF3B30',
    padding: 15,
    borderRadius: 5,
    marginTop: 20,
    alignItems: 'center',
  },
  connectButton: {
    backgroundColor: '#34C759',
    padding: 15,
    borderRadius: 5,
    marginTop: 10,
    alignItems: 'center',
  },
  buttonText: {
    color: 'white',
    fontWeight: 'bold',
  },
  codeContainer: {
    marginTop: 20,
    padding: 15,
    backgroundColor: '#f0f0f0',
    borderRadius: 5,
    alignItems: 'center',
    gap: 10,
  },
  clipboardBox: {
    marginTop: 10,
    padding: 15,
    borderColor: '#ccc',
    borderWidth: 1,
    borderRadius: 6,
    backgroundColor: '#fff',
    minHeight: 100,
  },
  input: {
    height: 40,
    width: '100%',
    borderColor: 'gray',
    borderWidth: 1,
    padding: 10,
    backgroundColor: 'white',
  },
});
