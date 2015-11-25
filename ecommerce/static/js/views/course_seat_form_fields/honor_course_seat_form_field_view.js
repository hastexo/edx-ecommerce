define([
        'views/course_seat_form_fields/course_seat_form_field_view',
        'raw!templates/honor_course_seat_form_field.html'
    ],
    function (CourseSeatFormFieldView,
              FieldTemplate) {
        'use strict';

        return CourseSeatFormFieldView.extend({
            certificateType: 'honor',
            idVerificationRequired: false,
            seatType: 'honor',
            template: _.template(FieldTemplate)
        });
    }
);
