(vl-load-com)

;;; -------------------------------------------------------------------------
;;; GLOBAL SETTINGS
;;; -------------------------------------------------------------------------
;;; Please replace "YOUR_GEMINI_API_KEY_HERE" with your actual Google Gemini API Key.
(setq *GEMINI-API-KEY* "YOUR_GEMINI_API_KEY_HERE")
(setq *GEMINI-MODEL* "gemini-1.5-flash") ; or gemini-pro

;;; -------------------------------------------------------------------------
;;; HELPER: Escape String for JSON
;;; Replaces backslashes and quotes to prevent JSON errors.
;;; -------------------------------------------------------------------------
(defun json-escape (str / len i char res)
  (setq len (strlen str))
  (setq i 1)
  (setq res "")
  (while (<= i len)
    (setq char (substr str i 1))
    (cond
      ((= char "\\") (setq res (strcat res "\\\\")))
      ((= char "\"") (setq res (strcat res "\\\"")))
      ((= char "\n") (setq res (strcat res "\\n")))
      ((= char "\r") (setq res (strcat res "\\r")))
      ((= char "\t") (setq res (strcat res "\\t")))
      (T (setq res (strcat res char)))
    )
    (setq i (1+ i))
  )
  res
)

;;; -------------------------------------------------------------------------
;;; HELPER: Unescape String from JSON
;;; Replaces \" with " and \\ with \
;;; -------------------------------------------------------------------------
(defun json-unescape (str / len i char next-char res)
  (setq len (strlen str))
  (setq i 1)
  (setq res "")
  (while (<= i len)
    (setq char (substr str i 1))
    (if (= char "\\")
      (progn
        (if (< i len)
          (progn
            (setq next-char (substr str (1+ i) 1))
            (cond
              ((= next-char "\"") (setq res (strcat res "\"")))
              ((= next-char "\\") (setq res (strcat res "\\")))
              ((= next-char "n") (setq res (strcat res "\n")))
              ((= next-char "r") (setq res (strcat res "\r")))
              ((= next-char "t") (setq res (strcat res "\t")))
              (T (setq res (strcat res char next-char))) ; Unknown escape, keep both
            )
            (setq i (1+ i))
          )
          (setq res (strcat res char)) ; Trailing backslash
        )
      )
      (setq res (strcat res char))
    )
    (setq i (1+ i))
  )
  res
)

;;; -------------------------------------------------------------------------
;;; HELPER: Extract Content from Gemini JSON Response
;;; A simple parser to find the "text" field inside the nested structure.
;;; Improved to handle escaped quotes inside the text.
;;; -------------------------------------------------------------------------
(defun extract-text-from-json (json-str / pos start i char escape len extracted)
  ;; The response usually looks like: ... "text": "Translated Text" ...
  ;; Depending on the API version, it might be nested under 'candidates' -> 'content' -> 'parts'.

  ;; Find "text": " (handling potential spacing variations is hard in pure lisp without regex,
  ;; but Gemini API output is usually consistent. We search for "text": and then find the opening quote).

  (setq pos (vl-string-search "\"text\":" json-str))
  (if pos
    (progn
      ;; Find the opening quote after "text":
      (setq start (vl-string-search "\"" json-str (+ pos 7)))

      (if start
        (progn
          (setq start (1+ start)) ; Move past the opening quote
          (setq len (strlen json-str))
          (setq i start)
          (setq escape nil)
          (setq extracted nil)

          ;; Loop until we find a non-escaped closing quote
          (while (and (not extracted) (<= i len))
            (setq char (substr json-str i 1))
            (if escape
              (setq escape nil) ; If previous char was backslash, this one is escaped, ignore it
              (if (= char "\\")
                (setq escape T) ; Found backslash, next char is escaped
                (if (= char "\"")
                  (setq extracted (substr json-str start (- i start))) ; Found closing quote
                )
              )
            )
            (setq i (1+ i))
          )

          (if extracted
            (json-unescape extracted) ; Clean up the escaped chars
            nil
          )
        )
        nil
      )
    )
    nil
  )
)

;;; -------------------------------------------------------------------------
;;; FUNCTION: Call Gemini API
;;; -------------------------------------------------------------------------
(defun call-gemini (text-to-translate / url httpObj payload prompt response status translatedText)

  (if (or (= *GEMINI-API-KEY* "") (= *GEMINI-API-KEY* "YOUR_GEMINI_API_KEY_HERE"))
    (progn
      (alert "Please edit the LISP file and insert your Gemini API Key.")
      nil
    )
    (progn
      (setq url (strcat "https://generativelanguage.googleapis.com/v1beta/models/" *GEMINI-MODEL* ":generateContent?key=" *GEMINI-API-KEY*))

      ;; Construct the prompt specifically for technical translation
      (setq prompt (strcat "Translate the following technical engineering text from English to Turkish. "
                           "Use precise technical terminology. "
                           "Return ONLY the translated text. Do not include markdown formatting or explanations. "
                           "Text: " text-to-translate))

      ;; JSON Payload construction
      (setq payload (strcat "{
        \"contents\": [{
          \"parts\": [{
            \"text\": \"" (json-escape prompt) "\"
          }]
        }]
      }"))

      ;; Setup HTTP Request Object
      (setq httpObj (vlax-create-object "WinHttp.WinHttpRequest.5.1"))

      (if httpObj
        (progn
          (vlax-invoke-method httpObj 'Open "POST" url :vlax-false)
          (vlax-invoke-method httpObj 'SetRequestHeader "Content-Type" "application/json")

          ;; Send Request. Capture errors if API fails.
          (if (vl-catch-all-error-p (vl-catch-all-apply 'vlax-invoke-method (list httpObj 'Send payload)))
            (progn
              (princ "\nError connecting to API.")
              nil
            )
            (progn
              (setq status (vlax-get-property httpObj 'Status))
              (setq response (vlax-get-property httpObj 'ResponseText))

              (if (= status 200)
                (progn
                  (setq translatedText (extract-text-from-json response))
                  (if (not translatedText)
                    (princ (strcat "\nFailed to parse response: " response))
                  )
                  translatedText
                )
                (progn
                  (princ (strcat "\nAPI Error " (itoa status) ": " response))
                  nil
                )
              )
            )
          )
        )
        (progn
          (princ "\nError: Cannot create WinHttp.WinHttpRequest object. Check Windows/AutoCAD version.")
          nil
        )
      )
    )
  )
)

;;; -------------------------------------------------------------------------
;;; MAIN COMMAND: TRGEMINI
;;; Selects text objects and translates them.
;;; -------------------------------------------------------------------------
(defun c:TRGEMINI ( / ss i ent obj oldText newText count)
  (princ "\nSelect Text or MText objects to translate (English -> Technical Turkish)...")
  (setq ss (ssget '((0 . "TEXT,MTEXT"))))

  (if ss
    (progn
      (setq count 0)
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq obj (vlax-ename->vla-object ent))
        (setq oldText (vla-get-textstring obj))

        (princ (strcat "\nTranslating: " oldText "..."))

        ;; Call API
        (setq newText (call-gemini oldText))

        (if (and newText (/= newText ""))
          (progn
            (vla-put-textstring obj newText)
            (princ " Done.")
            (setq count (1+ count))
          )
          (princ " Failed.")
        )

        (setq i (1+ i))
      )
      (alert (strcat "Translation Complete.\n" (itoa count) " objects translated."))
    )
    (princ "\nNo text objects selected.")
  )
  (princ)
)

(princ "\nType TRGEMINI to start the translation.")
(princ)
