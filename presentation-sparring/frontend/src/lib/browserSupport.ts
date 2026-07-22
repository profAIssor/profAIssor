export type BrowserSupportReason =
  | 'mobile_not_supported'
  | 'not_chrome'
  | 'insecure_context'
  | 'speech_recognition_missing'
  | 'media_devices_missing'
  | 'audio_context_missing'

export interface BrowserSupportResult {
  supported: boolean
  reason: BrowserSupportReason | null
  message: string | null
}

interface BrowserWindow extends Window {
  SpeechRecognition?: unknown
  webkitSpeechRecognition?: unknown
  webkitAudioContext?: typeof AudioContext
}

interface UserAgentDataLike {
  mobile?: boolean
  brands?: Array<{ brand: string; version: string }>
}

interface NavigatorWithUserAgentData extends Navigator {
  userAgentData?: UserAgentDataLike
}

/** 모바일 브라우저 여부 판정. */
function isMobileBrowser(): boolean {
  const navigatorWithData = navigator as NavigatorWithUserAgentData
  if (navigatorWithData.userAgentData?.mobile) return true

  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
}

/** Google Chrome 여부 판정. */
function isGoogleChrome(): boolean {
  const navigatorWithData = navigator as NavigatorWithUserAgentData
  const brands = navigatorWithData.userAgentData?.brands ?? []

  if (brands.length > 0) {
    return brands.some(({ brand }) => brand === 'Google Chrome')
  }

  const userAgent = navigator.userAgent
  const excluded =
    /Edg\/|OPR\/|SamsungBrowser\/|CriOS\/|FxiOS\/|Brave\//i.test(userAgent)

  return (
    navigator.vendor === 'Google Inc.' &&
    /Chrome\//i.test(userAgent) &&
    !excluded
  )
}

/** 현재 브라우저의 음성 스파링 지원 조건 판정. */
export function getBrowserSupport(): BrowserSupportResult {
  const browserWindow = window as BrowserWindow

  if (isMobileBrowser()) {
    return {
      supported: false,
      reason: 'mobile_not_supported',
      message:
        '모바일 Chrome 지원은 추후 추가될 예정입니다. 현재는 데스크톱 Google Chrome에서 이용해 주세요.',
    }
  }

  if (!isGoogleChrome()) {
    return {
      supported: false,
      reason: 'not_chrome',
      message:
        '현재 음성 스파링 기능은 데스크톱 Google Chrome에서만 지원합니다.',
    }
  }

  if (!window.isSecureContext) {
    return {
      supported: false,
      reason: 'insecure_context',
      message:
        '마이크 사용을 위해 HTTPS 주소 또는 localhost에서 접속해 주세요.',
    }
  }

  if (
    !browserWindow.SpeechRecognition &&
    !browserWindow.webkitSpeechRecognition
  ) {
    return {
      supported: false,
      reason: 'speech_recognition_missing',
      message:
        '현재 Chrome에서 음성인식 기능을 사용할 수 없습니다. Chrome을 최신 버전으로 업데이트해 주세요.',
    }
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    return {
      supported: false,
      reason: 'media_devices_missing',
      message:
        '현재 브라우저에서 마이크 입력 기능을 사용할 수 없습니다.',
    }
  }

  if (!window.AudioContext && !browserWindow.webkitAudioContext) {
    return {
      supported: false,
      reason: 'audio_context_missing',
      message:
        '현재 브라우저에서 음성 분석 기능을 사용할 수 없습니다.',
    }
  }

  return {
    supported: true,
    reason: null,
    message: null,
  }
}