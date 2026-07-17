Attribute VB_Name = "SendBOMToOdoo"
Option Explicit

' =====================================================================
' Inventor VBA macro: read the Parts List from the active .idw drawing,
' attach a matching image per part number from a local folder, and POST
' the whole BOM to the Odoo Inventor Connector REST API
' (POST /api/inventor/bom - see addons/inventor_connector/controllers/main.py).
'
' SETUP (one-time):
'   1. In Inventor: Tools > VBA Editor (Alt+F11).
'   2. Right-click the project > Insert > Module, paste this whole file.
'   3. Fill in the constants below (API key from Odoo: menu
'      "Inventor Connector > Settings"; Odoo DB name; image folder).
'   4. Open the .idw drawing that has the Parts List, then run the
'      macro "SendBOMToOdoo.SendPartsListToOdoo" (F5 or Tools > Macro).
'
' Column titles below ("ITEM", "PART NUMBER", "DESCRIPTION", "QTY") must
' match the actual column headers of the Parts List Style used in the
' drawing - rename the strings in BuildLinesJson if your style differs.
' =====================================================================

' ==================== CONFIGURATION ====================
Private Const API_URL As String = "http://localhost:8069/api/inventor/bom"
Private Const API_KEY As String = "PASTE_YOUR_API_KEY_HERE"
Private Const ODOO_DB As String = "jacon_plm"
Private Const BOM_TYPE As String = "panel_sticker"
Private Const IMAGE_FOLDER As String = "C:\InventorImages\"  ' must end with \ ; files named <PartNumber>.jpg/.png/...
' ========================================================

Public Sub SendPartsListToOdoo()
    Dim oDoc As DrawingDocument
    Dim oPartsList As PartsList
    Dim modelName As String
    Dim linesJson As String
    Dim jsonBody As String
    Dim result As String

    If ThisApplication.ActiveDocument Is Nothing Then
        MsgBox "Hay mo mot file .idw truoc khi chay macro nay.", vbExclamation
        Exit Sub
    End If
    If ThisApplication.ActiveDocument.DocumentType <> kDrawingDocumentObject Then
        MsgBox "File dang mo khong phai la ban ve (.idw).", vbExclamation
        Exit Sub
    End If

    Set oDoc = ThisApplication.ActiveDocument

    Set oPartsList = GetFirstPartsList(oDoc)
    If oPartsList Is Nothing Then
        MsgBox "Khong tim thay Parts List nao tren cac sheet cua ban ve nay.", vbExclamation
        Exit Sub
    End If

    modelName = GetModelName(oDoc)
    If Trim(modelName) = "" Then
        MsgBox "Da huy - can nhap Machine Model.", vbInformation
        Exit Sub
    End If

    linesJson = BuildLinesJson(oPartsList)

    jsonBody = "{" & _
        JQuote("model") & ":" & JQuote(modelName) & "," & _
        JQuote("bom_type") & ":" & JQuote(BOM_TYPE) & "," & _
        JQuote("name") & ":" & JQuote(oDoc.DisplayName) & "," & _
        JQuote("lines") & ":[" & linesJson & "]" & _
        "}"

    On Error GoTo ErrHandler
    result = PostJson(API_URL, jsonBody)
    MsgBox "Da gui xong." & vbCrLf & result, vbInformation
    Exit Sub

ErrHandler:
    MsgBox "Loi khi goi API: " & Err.Description, vbCritical
End Sub

Private Function GetFirstPartsList(oDoc As DrawingDocument) As PartsList
    Dim oSheet As Sheet
    For Each oSheet In oDoc.Sheets
        If oSheet.PartsLists.Count > 0 Then
            Set GetFirstPartsList = oSheet.PartsLists.Item(1)
            Exit Function
        End If
    Next
    Set GetFirstPartsList = Nothing
End Function

Private Function GetModelName(oDoc As DrawingDocument) As String
    Dim s As String
    On Error Resume Next
    s = oDoc.PropertySets.Item("Inventor User Defined Properties").Item("Model").Value
    On Error GoTo 0

    If Trim(s) = "" Then
        s = InputBox("Nhap Machine Model cho BOM nay (vi du: JSV6):", "Machine Model")
    End If
    GetModelName = Trim(s)
End Function

Private Function BuildLinesJson(oPartsList As PartsList) As String
    Dim oRow As PartsListRow
    Dim s As String
    Dim itemNo As String, partNo As String, desc As String, qty As String
    Dim imgPath As String, imgB64 As String
    Dim isFirst As Boolean
    isFirst = True

    For Each oRow In oPartsList.PartsListRows
        itemNo = "": partNo = "": desc = "": qty = ""
        On Error Resume Next
        itemNo = oRow.Item("ITEM")
        partNo = oRow.Item("PART NUMBER")
        desc = oRow.Item("DESCRIPTION")
        qty = oRow.Item("QTY")
        On Error GoTo 0

        If Not isFirst Then s = s & ","
        isFirst = False

        s = s & "{" & _
            JQuote("item") & ":" & CLngSafe(itemNo) & "," & _
            JQuote("part_number") & ":" & JQuote(partNo) & "," & _
            JQuote("description") & ":" & JQuote(desc) & "," & _
            JQuote("qty") & ":" & CLngSafe(qty)

        imgPath = FindImageFile(partNo)
        If imgPath <> "" Then
            imgB64 = Base64EncodeFile(imgPath)
            s = s & "," & JQuote("image") & ":" & JQuote(imgB64)
        End If

        s = s & "}"
    Next

    BuildLinesJson = s
End Function

Private Function FindImageFile(partNumber As String) As String
    Dim exts As Variant, ext As Variant
    Dim candidate As String

    If Trim(partNumber) = "" Then
        FindImageFile = ""
        Exit Function
    End If

    exts = Array("jpg", "jpeg", "png", "bmp", "gif")
    For Each ext In exts
        candidate = IMAGE_FOLDER & Trim(partNumber) & "." & ext
        If Dir(candidate) <> "" Then
            FindImageFile = candidate
            Exit Function
        End If
    Next
    FindImageFile = ""
End Function

Private Function Base64EncodeFile(filePath As String) As String
    Dim oStream As Object  ' ADODB.Stream
    Dim oXML As Object     ' MSXML2.DOMDocument
    Dim oNode As Object

    Set oStream = CreateObject("ADODB.Stream")
    oStream.Type = 1 ' adTypeBinary
    oStream.Open
    oStream.LoadFromFile filePath

    Set oXML = CreateObject("MSXML2.DOMDocument")
    Set oNode = oXML.createElement("b64")
    oNode.DataType = "bin.base64"
    oNode.nodeTypedValue = oStream.Read

    Base64EncodeFile = Replace(Replace(oNode.text, vbCr, ""), vbLf, "")

    oStream.Close
    Set oStream = Nothing
End Function

Private Function CLngSafe(s As String) As String
    If IsNumeric(Trim(s)) Then
        CLngSafe = CStr(CLng(Trim(s)))
    Else
        CLngSafe = "0"
    End If
End Function

Private Function JQuote(v As Variant) As String
    Dim t As String
    t = CStr(v)
    t = Replace(t, "\", "\\")
    t = Replace(t, Chr(34), "\" & Chr(34))
    t = Replace(t, vbCrLf, "\n")
    t = Replace(t, vbCr, "\n")
    t = Replace(t, vbLf, "\n")
    t = Replace(t, vbTab, "\t")
    JQuote = Chr(34) & t & Chr(34)
End Function

Private Function PostJson(url As String, jsonBody As String) As String
    Dim oHttp As Object
    Set oHttp = CreateObject("WinHttp.WinHttpRequest.5.1")
    oHttp.Open "POST", url, False
    oHttp.SetRequestHeader "Content-Type", "application/json"
    oHttp.SetRequestHeader "X-API-Key", API_KEY
    oHttp.SetRequestHeader "X-Odoo-Database", ODOO_DB
    oHttp.Send jsonBody
    PostJson = "HTTP " & oHttp.Status & vbCrLf & oHttp.responseText
End Function
