import request from '../utils/request.js'

export const listMarketWatches = () => request.get('/market/watches')
export const addMarketWatch = body => request.post('/market/watches', body)
export const collectMarketWatch = id => request.post(`/market/watches/${id}/collect`, {}, { timeout: 180000 })
export const listMarketTrends = (watchId, days = 7) => request.get('/market/trends', { params: { watchId, days } })
export const addMarketQuote = body => request.post('/market/quotes', body)
export const listMarketComparisons = itemId => request.get('/market/comparisons', { params: { itemId } })
