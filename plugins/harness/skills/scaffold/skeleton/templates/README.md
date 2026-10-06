# templates

고객사에게 받은 Template 원본을 받은 그대로 넣는다. 파일명은 바꾸지 않아도
된다.

`rules/*.yaml` 의 `템플릿:` 이 여기를 `../templates/<파일>` 로 가리킨다.

`templates/harness/` 는 harness 자신이 쓰는 템플릿이 사는 자리다(Audit 기록
등). 지우지 않는다. 고객사 템플릿은 이 폴더와 섞지 않고 바로 이 옆에 둔다.

`templates/forms/` 는 양식 지도(`<양식 이름>.yaml`)가 사는 자리다. 양식 지도는
고객사 양식(xlsx 등)의 시트·칸·표·서술 위치를 적은 파일이고, `/harness:spec`
이 개발 Spec 에 양식 항목을 채울 때 읽는다. 형식은 harness Plugin 의
`skills/spec/form-map.md` 에 있다. 양식 지도는 doc-guard 검사 대상이 아니다.
