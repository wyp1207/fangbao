/** 巡检照片路径归一化：库里存相对路径，接口在 /api/v1/inspection/photos/。 */
export function inspectionPhotoUrl(u: string): string {
  if (!u) return ''
  if (/^(https?:)?\/\//i.test(u) || u.startsWith('/')) return u
  return `/api/v1/inspection/photos/${u.replace(/^inspection_photos\//, '')}`
}
