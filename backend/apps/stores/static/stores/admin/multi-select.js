'use strict';
{
    const $ = django.jQuery;
    $(function() {
        $('select[data-multi-select]').each(function() {
            $(this).select2({width: '24em', placeholder: this.dataset.placeholder || ''});
        });
    });
}
