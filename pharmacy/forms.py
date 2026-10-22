from django import forms
from .models import Medicine
class MedicineForm(forms.ModelForm):
    class Meta:
        model = Medicine
        fields = ['name','generic_name','category','image','strength','batch_number','expiry_date','purchase_price','selling_price','quantity','minimum_stock','requires_prescription','active']
        widgets = {'expiry_date': forms.DateInput(attrs={'type':'date','class':'form-control'}), 'requires_prescription': forms.CheckboxInput(attrs={'class':'form-check-input'}), 'active': forms.CheckboxInput(attrs={'class':'form-check-input'})}
        formlabels = None
    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image and image.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Medicine image must be 5 MB or smaller.')
        if image and getattr(image, 'content_type', '') not in {'image/jpeg', 'image/png', 'image/webp'}:
            raise forms.ValidationError('Upload a JPG, PNG, or WebP image.')
        return image

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['image'].widget.attrs.update({'accept': 'image/jpeg,image/png,image/webp'})
        for name, field in self.fields.items():
            if name not in ('requires_prescription','active','expiry_date'):
                field.widget.attrs['class'] = 'form-control'
