package com.klicklab.common;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HomeController {

    @GetMapping(value = "/", produces = "text/html;charset=UTF-8")
    public String home() {
        return "Welcome to the KlickLab!";
    }
}
