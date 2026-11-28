// ------------------------------------------------------------
// API KATMANI (tek giriş noktası)
// Ekranlar veriyi SADECE bu dosyadan ister.
//
//   npm run dev        → Demo modu  → mockApi.js : örnek veri
//   npm run dev:canli  → Canlı mod  → liveApi.js : ekibin FastAPI backend'i
//
// (Vite "--mode canli" ile başlatılınca MODE = 'canli' olur.)
// ------------------------------------------------------------
import * as mockApi from './mockApi.js'
import * as liveApi from './liveApi.js'

const ENV = import.meta.env || {}
export const USE_MOCK = !(ENV.MODE === 'canli' || String(ENV.VITE_USE_MOCK) === 'false')
const impl = USE_MOCK ? mockApi : liveApi

export const features = impl.features

// Oturum
export const login = (...a) => impl.login(...a)
export const register = (...a) => impl.register(...a)
export const logout = (...a) => impl.logout(...a)

// Dersler ve kazanımlar
export const getCourses = (...a) => impl.getCourses(...a)
export const createCourse = (...a) => impl.createCourse(...a)
export const deleteCourse = (...a) => impl.deleteCourse(...a)
export const getOutcomes = (...a) => impl.getOutcomes(...a)
export const addOutcome = (...a) => impl.addOutcome(...a)
export const deleteOutcome = (...a) => impl.deleteOutcome(...a)
export const addPrerequisite = (...a) => impl.addPrerequisite(...a)

// Soru bankası
export const getQuestions = (...a) => impl.getQuestions(...a)
export const addQuestion = (...a) => impl.addQuestion(...a)
export const updateQuestion = (...a) => impl.updateQuestion(...a)
export const deleteQuestion = (...a) => impl.deleteQuestion(...a)

// Ders materyalleri
export const getMaterials = (...a) => impl.getMaterials(...a)
export const addMaterial = (...a) => impl.addMaterial(...a)
export const uploadMaterial = (...a) => impl.uploadMaterial(...a)
export const deleteMaterial = (...a) => impl.deleteMaterial(...a)

// Sınavlar
export const getInitialExam = (...a) => impl.getInitialExam(...a)
export const submitInitialExam = (...a) => impl.submitInitialExam(...a)
export const getRetestOptions = (...a) => impl.getRetestOptions(...a)
export const getRetest = (...a) => impl.getRetest(...a)
export const submitRetest = (...a) => impl.submitRetest(...a)

// Harita ve öneriler
export const getLearningMap = (...a) => impl.getLearningMap(...a)
export const getRecommendation = (...a) => impl.getRecommendation(...a)
export const checkBackendHealth = (...a) => impl.checkBackendHealth(...a)
export const buildAnalysisRequest = (...a) => impl.buildAnalysisRequest(...a)

// Asistan
export const askAssistant = (...a) => impl.askAssistant(...a)

// Akademisyen raporları
export const getClassReport = (...a) => impl.getClassReport(...a)
export const updateThresholds = (...a) => impl.updateThresholds(...a)

// Yönetici
export const getUsers = (...a) => impl.getUsers(...a)
export const updateUser = (...a) => impl.updateUser(...a)
export const addUser = (...a) => impl.addUser(...a)

// Yardımcılar (testler ve demo)
export const resetDemo = (...a) => impl.resetDemo(...a)
export const setAnalysisUrl = (...a) => impl.setAnalysisUrl(...a)
