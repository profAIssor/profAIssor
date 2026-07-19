import { Plus, Upload, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { extractSlides } from '../api'
import type { Slide } from '../types'

interface Props {
  slides: Slide[]
  onChange: (slides: Slide[]) => void
}

/** 슬라이드 텍스트 추가·삭제·수정 및 PPT 업로드 입력 목록 */
export default function SlideInput({ slides, onChange }: Props) {
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    setUploading(true)
    setUploadError(null)

    try {
      const extracted = await extractSlides(file)
      onChange(extracted)
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const update = (i: number, text: string) => {
    const next = slides.map((s, idx) => (idx === i ? { ...s, text } : s))
    onChange(next)
  }

  const add = () => {
    onChange([...slides, { index: slides.length + 1, text: '' }])
  }

  const remove = (i: number) => {
    const next = slides
      .filter((_, idx) => idx !== i)
      .map((s, idx) => ({ ...s, index: idx + 1 }))

    onChange(next)
  }

  return (
    <div className="space-y-3">
      <label
        className={
          'flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 ' +
          (uploading ? 'pointer-events-none opacity-50' : '')
        }
      >
        <Upload className="h-4 w-4" />
        {uploading ? 'PPT에서 추출하는 중…' : 'PPT 업로드 (.pptx)'}
        <input
          ref={fileInputRef}
          type="file"
          accept=".pptx"
          className="hidden"
          disabled={uploading}
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void handleFile(file)
          }}
        />
      </label>

      {uploadError && (
        <div className="rounded-xl border border-rose-100 bg-rose-50 px-4 py-2.5 text-sm text-rose-600">
          {uploadError}
        </div>
      )}

      {slides.map((slide, i) => (
        <div key={i} className="flex gap-2">
          <span className="mt-2 w-16 shrink-0 text-sm font-semibold text-indigo-600">
            슬라이드 {slide.index}
          </span>
          <textarea
            value={slide.text}
            onChange={(e) => update(i, e.target.value)}
            placeholder="이 슬라이드의 핵심 텍스트 (제목/불릿 요점)"
            rows={2}
            className="flex-1 resize-y rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2 text-sm text-slate-700 outline-none focus:border-indigo-500 focus:bg-white focus:ring-2 focus:ring-indigo-500"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            className="mt-1 h-8 w-8 shrink-0 rounded-lg border border-slate-200 text-slate-400 hover:border-rose-400 hover:text-rose-500"
            aria-label="슬라이드 삭제"
          >
            <X className="mx-auto h-4 w-4" />
          </button>
        </div>
      ))}

      <button
        type="button"
        onClick={add}
        className="flex items-center gap-1 text-sm font-medium text-slate-400 hover:text-indigo-600"
      >
        <Plus className="h-3.5 w-3.5" />
        슬라이드 직접 추가
      </button>
    </div>
  )
}
